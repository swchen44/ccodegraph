#!/usr/bin/env python3
"""tools/run_hard_ab_v3.py — R4 v3:全 22 題 x 4 工具(none/ccodegraph/codegraph/cbm),
統一用 `claude-sonnet-5`,ccodegraph 這次一律用真實 compile_commands.json
(redis 既有的 bear 產出;wpa 這次新建的 CONFIG_DRIVER_WIRED+CONFIG_SAE+CONFIG_AP
build,driver_nl80211.c 因 macOS 缺 Linux 核心 header 而確認缺席,已知限制)。

沿用 `run_hard_ab.py`/`run_hard_ab_armc.py`/`run_hard_ab_thirdparty.py` 的隔離
手法(git archive HEAD 乾淨複本、`--setting-sources project` 跳過使用者全域
skill)。題目直接從 `docs/research/hard-benchmark/questions.jsonl` 讀取(單一
真相來源,不重複貼文字避免版本漂移)。

cbm 隔離修正:先前 v2 對照跑 WRQ-009 時,cbm 臂曾意外用 CBM_BIN 的絕對路徑
拼出 `.../cbm-fork/../` 跳出乾淨複本、讀到未隔離的原始 checkout(內容剛好沒被
污染,答案未受影響,但這是真實的隔離漏洞)。這次 prompt 明確加一句「唯一該讀
的原始碼在你目前工作目錄 `.`,cbm 執行檔本身在磁碟上別處,不要把它的路徑當成
原始碼位置的線索」。

用法:python3 tools/run_hard_ab_v3.py <out_dir> [WRQ-0XX ...]
不帶題號跑全部 22 題 x 4 工具(88 次);帶題號只跑指定題,方便分段執行
(這正是使用者要求的「需要分段」)。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

CCODEGRAPH_REPO = os.path.expanduser("~/git/ccodegraph")
CCODEGRAPH_PY = os.path.join(CCODEGRAPH_REPO, "ccodegraph.py")
SKILL_MD = os.path.join(CCODEGRAPH_REPO, "skills/ccodegraph/SKILL.md")
CLINK_BIN = os.path.expanduser("~/git/clink/build/clink/clink")
QUESTIONS_JSONL = os.path.join(
    CCODEGRAPH_REPO, "docs/research/hard-benchmark/questions.jsonl")

CG_BIN = os.path.expanduser("~/.local/bin/codegraph")
CBM_BIN = os.path.expanduser(
    "~/git/cbm-vs-codegraph-bench/repos/cbm-fork/build/c/codebase-memory-mcp")

REPOS = {
    "wpa": os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/wpa_supplicant"),
    "redis": os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis"),
}
REAL_COMPDB = {
    "wpa": os.path.join(REPOS["wpa"], "compile_commands.json"),
    "redis": os.path.join(REPOS["redis"], "compile_commands.json"),
}
MODEL = "claude-sonnet-5"
TOOLS = ("none", "ccodegraph", "codegraph", "cbm")

NONE_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。只能用 shell 指令(grep/awk/sed/cat/find/"
    "Read)探索原始碼,不要安裝或呼叫任何額外工具,也不要嘗試連網。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")

CCODEGRAPH_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有 ./ccodegraph.py 這個程式碼知識圖"
    "工具,圖已經建好在 .ccodegraph/(這次用真實 compile_commands.json 建圖,"
    "非合成)。請用它來回答,必要時可以搭配它的 sql 逃生口或少量 grep 覆核可疑"
    "答案。任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")

CODEGRAPH_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有第三方工具 CodeGraph,已經在 "
    "`.codegraph/` 建好索引(`codegraph init` 已跑完)。可用指令(絕對路徑 "
    f"{CG_BIN}):\n"
    f"  {CG_BIN} query <search> -p . -j        # 搜尋符號\n"
    f"  {CG_BIN} node <name> -p . -j           # 單一符號原始碼+呼叫者/被呼叫\n"
    f"  {CG_BIN} callers <symbol> -p . -j      # 誰呼叫這個符號\n"
    f"  {CG_BIN} callees <symbol> -p . -j      # 這個符號呼叫誰\n"
    f"  {CG_BIN} impact <symbol> -d 3 -p . -j  # 影響範圍(呼叫鏈往外展開)\n"
    f"  {CG_BIN} explore \"<query>\" -p .        # 一句話拿相關原始碼+呼叫路徑\n"
    "也可以直接 `sqlite3 .codegraph/codegraph.db` 查 nodes/edges 表。必要時可"
    "搭配少量 grep/cat 覆核可疑答案。任務:{question} 回答精簡但完整,不要省略"
    "你找到的細節列表。不要修改任何檔案。")

CBM_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有第三方工具 cbm"
    "(codebase-memory-mcp,語意知識圖),已經建好索引。可用指令(絕對路徑 "
    "{cbm_bin},cache 目錄 {cache},專案名稱 {proj}):\n"
    "  CBM_CACHE_DIR={cache} {cbm_bin} cli query_graph "
    "'{{\"project\":\"{proj}\",\"query\":\"<openCypher>\"}}'\n"
    "  CBM_CACHE_DIR={cache} {cbm_bin} cli trace_path "
    "'{{\"project\":\"{proj}\",\"function_name\":\"<fn>\","
    "\"direction\":\"inbound|outbound\",\"depth\":3}}'\n"
    "節點 label:Function/Class(對應 struct)/Field/Variable/Macro/File/Module "
    "等;CALLS 邊在這個 C 專案上經常掛在檔案節點而非函式節點。"
    "**重要:唯一該探索的原始碼在你目前工作目錄 `.`;cbm 執行檔本身在磁碟上"
    "別處,那個路徑只是拿來呼叫程式用的,不是原始碼位置的線索,不要據此 cd 或"
    "組出其他路徑。**必要時可搭配少量 grep/cat 覆核可疑答案。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")


def load_questions() -> list[dict[str, Any]]:
    with open(QUESTIONS_JSONL) as f:
        return [json.loads(line) for line in f if line.strip()]


def clean_copy(src: str, dst: str) -> None:
    r = subprocess.run(f"git archive HEAD | tar -x -C {dst!r}",
                       shell=True, cwd=src, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: git archive failed for {src}: {r.stderr}")


def run_claude(prompt: str, cwd: str, out_path: str, env: dict[str, str],
              budget: float = 3.0) -> tuple[float, int]:
    cmd = ["claude", "-p", prompt, "--setting-sources", "project",
          "--output-format", "json", "--permission-mode", "bypassPermissions",
          "--model", MODEL, "--max-budget-usd", str(budget)]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                      timeout=1200, env=env)
    dt = time.time() - t0
    with open(out_path, "w") as f:
        f.write(r.stdout)
    if r.returncode != 0:
        with open(out_path + ".stderr", "w") as f:
            f.write(r.stderr)
    return dt, r.returncode


def prep_none(q: dict[str, Any], tmp: str) -> str:
    clean_copy(REPOS[q["repo"]], tmp)
    return NONE_TEMPLATE.format(question=q["question"])


def prep_ccodegraph(q: dict[str, Any], tmp: str) -> str:
    clean_copy(REPOS[q["repo"]], tmp)
    shutil.copy(CCODEGRAPH_PY, tmp)
    real_db = REAL_COMPDB[q["repo"]]
    if os.path.exists(real_db):
        shutil.copy(real_db, os.path.join(tmp, "compile_commands.json"))
    os.makedirs(os.path.join(tmp, ".claude", "skills", "ccodegraph"),
               exist_ok=True)
    shutil.copy(SKILL_MD,
               os.path.join(tmp, ".claude", "skills", "ccodegraph", "SKILL.md"))
    subprocess.run(["python3", "ccodegraph.py", "build", "-p", ".", "-j", "8"],
                  cwd=tmp, check=True, capture_output=True)
    if os.path.exists(CLINK_BIN):
        env = {**os.environ, "CCODEGRAPH_CLINK_PATH": CLINK_BIN}
        subprocess.run(["python3", "ccodegraph.py", "clink-import", "-p", "."],
                      cwd=tmp, env=env, capture_output=True)
    return CCODEGRAPH_TEMPLATE.format(question=q["question"])


def prep_codegraph(q: dict[str, Any], tmp: str) -> str:
    clean_copy(REPOS[q["repo"]], tmp)
    env = {**os.environ, "CODEGRAPH_TELEMETRY": "0"}
    subprocess.run([CG_BIN, "init", "."], cwd=tmp, env=env,
                  check=True, capture_output=True)
    return CODEGRAPH_TEMPLATE.format(question=q["question"])


def prep_cbm(q: dict[str, Any], tmp: str) -> str:
    clean_copy(REPOS[q["repo"]], tmp)
    cache = os.path.join(tmp, ".cbm-cache")
    os.makedirs(cache, exist_ok=True)
    subprocess.run([CBM_BIN, "--json", "cli", "index_repository",
                   json.dumps({"repo_path": tmp, "mode": "full"})],
                  env={**os.environ, "CBM_CACHE_DIR": cache},
                  check=True, capture_output=True)
    proj = next(f for f in os.listdir(cache) if f.endswith(".db"))[:-3]
    return CBM_TEMPLATE.format(cbm_bin=CBM_BIN, cache=cache, proj=proj,
                              question=q["question"])


PREP = {
    "none": prep_none,
    "ccodegraph": prep_ccodegraph,
    "codegraph": prep_codegraph,
    "cbm": prep_cbm,
}


def summarize(out_path: str) -> dict[str, Any]:
    try:
        with open(out_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}
    u = data.get("usage", {})
    return {
        "cost_usd": data.get("total_cost_usd"),
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
        "num_turns": data.get("num_turns"),
        "duration_ms": data.get("duration_ms"),
        "is_error": data.get("is_error"),
        "session_id": data.get("session_id"),
        "model_usage_keys": list(data.get("modelUsage", {}).keys()),
    }


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-ab-v3"
    only = set(sys.argv[2:]) or None
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "summary.json")
    summary: list[dict[str, Any]] = []
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
    done = {(s["id"], s["tool"]) for s in summary if s.get("rc") == 0}

    questions = load_questions()
    for q in questions:
        if only and q["id"] not in only:
            continue
        for tool in TOOLS:
            if (q["id"], tool) in done:
                print(f"=== {q['id']} tool={tool} — already done, skip ===",
                     flush=True)
                continue
            print(f"=== {q['id']} tool={tool} ({q['repo']}) ===", flush=True)
            tmp = tempfile.mkdtemp()
            try:
                prompt = PREP[tool](q, tmp)
                env = dict(os.environ)
                out_path = os.path.join(out_dir, f"{q['id']}_{tool}.json")
                dt, rc = run_claude(prompt, tmp, out_path, env)
                s = summarize(out_path)
                s.update({"id": q["id"], "tool": tool, "wall_s": round(dt, 1),
                          "rc": rc})
                summary = [x for x in summary
                          if not (x["id"] == q["id"] and x["tool"] == tool)]
                summary.append(s)
                with open(summary_path, "w") as f:
                    json.dump(summary, f, indent=2)
                print(f"    done in {dt:.0f}s rc={rc} "
                     f"cost=${s.get('cost_usd')} "
                     f"tokens_in={s.get('input_tokens')} "
                     f"tokens_out={s.get('output_tokens')} "
                     f"models={s.get('model_usage_keys')}", flush=True)
            except subprocess.CalledProcessError as e:
                print(f"    PREP FAILED: {e}", flush=True)
                summary.append({"id": q["id"], "tool": tool, "rc": -1,
                               "error": str(e)})
                with open(summary_path, "w") as f:
                    json.dump(summary, f, indent=2)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    print("\n=== final summary ===")
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
