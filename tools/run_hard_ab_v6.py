#!/usr/bin/env python3
"""tools/run_hard_ab_v6.py — v6:claude+LSP(clangd/真實 compile DB)對決。

三臂同場重跑(使用者拍板):none(=claude grep)/ ccodegraph(0.0.6,D17
直讀)/ lsp(Claude Code 原生 LSP plugin + clangd + 真實 compile_commands.json,
out-of-box:prompt 只給 README 級工具說明,與 v3 給 codegraph/cbm 的待遇一致)。
N=3(summary key = id, tool, rep)。codegraph/cbm 沿用 v3/v4 舊數據不重跑。

隔離沿用 v3:git archive 乾淨複本、`--setting-sources project`。lsp 臂差異:
- 固定工作樹(非每 run 重解):clangd background index 的 .cache/clangd/ 以
  絕對路徑為鍵,重解樹會全量重建;比照 v5「預建索引跨 run 重用」政策,
  每 run 用指紋(檔數+哨兵 hash)驗樹未被污染,髒了自動重備。
- compile_commands.json 路徑重寫:directory/file/output/arguments 內的舊
  checkout 前綴改寫到工作樹(wpa 的 112 entries 全帶絕對 -I)。
- .claude/settings.json 啟用 clangd-lsp@local-bench plugin(project scope;
  marketplace 已在 user config 註冊,實測 --setting-sources project 下可解析)。
- clangd 預熱:啟 clangd --background-index、LSP initialize、輪詢
  .cache/clangd/index shard 數至穩定;預熱牆鐘計入索引成本表(index_meta)。

用法:python3 tools/run_hard_ab_v6.py <out_dir> [WRQ-0XX ...] [tools=a,b]
      [reps=N]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

CCODEGRAPH_REPO = os.path.expanduser("~/git/ccodegraph")
CCODEGRAPH_PY = os.path.join(CCODEGRAPH_REPO, "ccodegraph.py")
SKILL_MD = os.path.join(CCODEGRAPH_REPO, "skills/ccodegraph/SKILL.md")
CLINK_BIN = os.path.expanduser("~/git/clink/build/clink/clink")
QUESTIONS_JSONL = os.path.join(
    CCODEGRAPH_REPO, "docs/research/hard-benchmark/questions.jsonl")

REPOS = {
    "wpa": os.path.expanduser(
        "~/git/cbm-vs-codegraph-bench/repos/wpa_supplicant"),
    "redis": os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis"),
}
REAL_COMPDB = {k: os.path.join(v, "compile_commands.json")
               for k, v in REPOS.items()}
MODEL = "claude-sonnet-5"
TOOLS = ("none", "ccodegraph", "lsp", "lspskill")
N_REPS = 3
V6_WORK = os.path.expanduser("~/kernel-bench/v6-lsp")
LSP_PLUGIN_KEY = "clangd-lsp@local-bench"

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

# out-of-box 原則:README 級說明(工具存在、操作清單、參數形狀、載入方式),
# 與 v3 給 codegraph 的 CLI cheatsheet 同一待遇;不教策略、不教陷阱。
LSP_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這個環境已啟用 clangd LSP(讀取專案根"
    "的真實 compile_commands.json,單一建置組態,索引已預熱)。有一個 `LSP` "
    "工具(若不在目前工具清單,先用 ToolSearch query=\"select:LSP\" 載入),"
    "操作:goToDefinition / findReferences / hover / documentSymbol / "
    "workspaceSymbol / goToImplementation / prepareCallHierarchy / "
    "incomingCalls / outgoingCalls;參數 filePath + line + character"
    "(1-based;workspaceSymbol 另用 query 參數)。請優先用 LSP 工具回答,"
    "必要時可搭配少量 grep/cat 覆核可疑答案。"
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


# ---------- lsp 臂:固定工作樹 + 一次性預熱 ----------

def rewrite_compdb(src_db: str, old_root: str, new_root: str,
                   dst_db: str) -> int:
    with open(src_db) as f:
        db = json.load(f)
    def rw(s: str) -> str:
        return s.replace(old_root, new_root)
    for e in db:
        for key in ("directory", "file", "output", "command"):
            if key in e:
                e[key] = rw(e[key])
        if "arguments" in e:
            e["arguments"] = [rw(a) for a in e["arguments"]]
    with open(dst_db, "w") as f:
        json.dump(db, f, indent=1)
    return len(db)


def lsp_prewarm(root: str, timeout: float = 900.0) -> tuple[float, int]:
    """啟 clangd --background-index,initialize 後輪詢 index shard 數至
    穩定(20 秒無變化)或 timeout。回 (牆鐘秒, shard 數)。
    stdout 必須有人排水,否則 clangd 塞管死鎖。"""
    proc = subprocess.Popen(
        ["clangd", "--background-index", "--log=error"],
        cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    assert proc.stdout is not None and proc.stdin is not None
    threading.Thread(target=lambda: proc.stdout.read(),  # type: ignore[union-attr]
                     daemon=True).start()

    def send(obj: dict[str, Any]) -> None:
        data = json.dumps(obj).encode()
        assert proc.stdin is not None
        proc.stdin.write(
            f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        proc.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"processId": os.getpid(),
                     "rootUri": "file://" + root, "capabilities": {}}})
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    # clangd 惰性載入 compile DB:必須 didOpen 一個 DB 內的檔案,
    # background index 才會啟動(實測 Apple clangd 17;漏這步 = 0 shards)
    # 選第一個「真實存在」的 DB 條目(bear 產出含 configure 探測的幽靈
    # 條目,如 redis 的 foo.c x4);file 可為相對 directory 的路徑
    with open(os.path.join(root, "compile_commands.json")) as f:
        entries = json.load(f)
    first = None
    for e0 in entries:
        cand = e0["file"]
        if not os.path.isabs(cand):
            cand = os.path.normpath(os.path.join(e0["directory"], cand))
        if os.path.exists(cand):
            first = cand
            break
    assert first, "compile DB 沒有任何存在的檔案"
    with open(first, encoding="utf-8", errors="replace") as f:
        text = f.read()
    send({"jsonrpc": "2.0", "method": "textDocument/didOpen",
          "params": {"textDocument": {"uri": "file://" + first,
                                      "languageId": "c", "version": 1,
                                      "text": text}}})
    idx_dir = os.path.join(root, ".cache", "clangd", "index")
    t0 = time.time()
    last, stable = -1, 0
    while time.time() - t0 < timeout:
        n = len(os.listdir(idx_dir)) if os.path.isdir(idx_dir) else 0
        if n == last and n > 0:
            stable += 1
            if stable >= 10:          # 10 x 2s 無變化 → 視為完成
                break
        else:
            stable, last = 0, n
        time.sleep(2)
    proc.kill()
    return time.time() - t0, max(last, 0)


def _fingerprint(root: str, repo: str) -> dict[str, Any]:
    sentinels = {
        "wpa": ["src/utils/eloop.c", "wpa_supplicant/events.c"],
        "redis": ["src/server.c", "src/t_string.c"],
    }[repo]
    n_files = sum(len(fs) for _, _, fs in os.walk(root))
    hashes = {}
    for s in sentinels:
        p = os.path.join(root, s)
        with open(p, "rb") as f:
            hashes[s] = hashlib.sha256(f.read()).hexdigest()
    return {"n_files": n_files, "hashes": hashes}


def lsp_workdir(repo: str, variant: str = "lsp") -> str:
    return os.path.join(V6_WORK, f"work-{variant}-{repo}")


# lspskill 臂(精調教學層實驗):與 lsp 臂唯一差異 = 種入
# .claude/skills/lsp-nav/SKILL.md(prompt 一字不改,單變因)。
LSP_SKILL_SRC = os.path.join(V6_WORK, "skill", "SKILL-current.md")


def prep_lsp_tree(repo: str, variant: str = "lsp") -> None:
    """固定工作樹一次性準備;已備好且指紋相符 → 直接重用。"""
    root = lsp_workdir(repo, variant)
    meta_path = os.path.join(V6_WORK, f"{variant}-index-meta-{repo}.json")
    fp_path = os.path.join(V6_WORK, f"{variant}-fingerprint-{repo}.json")
    if os.path.exists(fp_path) and os.path.isdir(root):
        with open(fp_path) as f:
            want = json.load(f)
        try:
            if _fingerprint(root, repo) == want and os.path.isdir(
                    os.path.join(root, ".cache", "clangd", "index")):
                return
        except OSError:
            pass
        print(f"    [{variant}] {repo} 工作樹指紋不符/快取缺失 → 重備",
              flush=True)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    clean_copy(REPOS[repo], root)
    n = rewrite_compdb(REAL_COMPDB[repo], REPOS[repo], root,
                       os.path.join(root, "compile_commands.json"))
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    with open(os.path.join(root, ".claude", "settings.json"), "w") as f:
        json.dump({"enabledPlugins": {LSP_PLUGIN_KEY: True}}, f, indent=2)
    if variant == "lspskill":
        sk_dir = os.path.join(root, ".claude", "skills", "lsp-nav")
        os.makedirs(sk_dir, exist_ok=True)
        shutil.copy(LSP_SKILL_SRC, os.path.join(sk_dir, "SKILL.md"))
    print(f"    [{variant}] {repo}: compile DB {n} entries,預熱 clangd 索引…",
          flush=True)
    wall, shards = lsp_prewarm(root)
    with open(meta_path, "w") as f:
        json.dump({"repo": repo, "compdb_entries": n,
                   "prewarm_wall_s": round(wall, 1),
                   "index_shards": shards}, f, indent=2)
    with open(fp_path, "w") as f:
        json.dump(_fingerprint(root, repo), f, indent=2)
    print(f"    [{variant}] {repo}: 預熱 {wall:.0f}s,index shards={shards}",
          flush=True)


# ---------- 三臂 prep(回傳 prompt, cwd, 是否用完即刪) ----------

def prep_none(q: dict[str, Any]) -> tuple[str, str, bool]:
    tmp = tempfile.mkdtemp()
    clean_copy(REPOS[q["repo"]], tmp)
    return NONE_TEMPLATE.format(question=q["question"]), tmp, True


def prep_ccodegraph(q: dict[str, Any]) -> tuple[str, str, bool]:
    tmp = tempfile.mkdtemp()
    clean_copy(REPOS[q["repo"]], tmp)
    shutil.copy(CCODEGRAPH_PY, tmp)
    real_db = REAL_COMPDB[q["repo"]]
    if os.path.exists(real_db):
        shutil.copy(real_db, os.path.join(tmp, "compile_commands.json"))
    os.makedirs(os.path.join(tmp, ".claude", "skills", "ccodegraph"),
                exist_ok=True)
    shutil.copy(SKILL_MD,
                os.path.join(tmp, ".claude", "skills", "ccodegraph",
                             "SKILL.md"))
    subprocess.run(["python3", "ccodegraph.py", "build", "-p", ".", "-j", "8"],
                   cwd=tmp, check=True, capture_output=True)
    if os.path.exists(CLINK_BIN):
        env = {**os.environ, "CCODEGRAPH_CLINK_PATH": CLINK_BIN}
        subprocess.run(["python3", "ccodegraph.py", "clink-import", "-p", "."],
                       cwd=tmp, env=env, capture_output=True)
    return CCODEGRAPH_TEMPLATE.format(question=q["question"]), tmp, True


def prep_lsp(q: dict[str, Any]) -> tuple[str, str, bool]:
    prep_lsp_tree(q["repo"])
    return (LSP_TEMPLATE.format(question=q["question"]),
            lsp_workdir(q["repo"]), False)


def prep_lspskill(q: dict[str, Any]) -> tuple[str, str, bool]:
    prep_lsp_tree(q["repo"], variant="lspskill")
    return (LSP_TEMPLATE.format(question=q["question"]),
            lsp_workdir(q["repo"], "lspskill"), False)


PREP = {"none": prep_none, "ccodegraph": prep_ccodegraph, "lsp": prep_lsp,
        "lspskill": prep_lspskill}


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
        "duration_api_ms": data.get("duration_api_ms"),
        "is_error": data.get("is_error"),
        "session_id": data.get("session_id"),
        "model_usage_keys": list(data.get("modelUsage", {}).keys()),
    }


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-ab-v6"
    tool_filter: tuple[str, ...] = TOOLS
    n_reps = N_REPS
    rest = []
    for a in sys.argv[2:]:
        if a.startswith("tools="):
            tool_filter = tuple(a.split("=", 1)[1].split(","))
            assert all(t in TOOLS for t in tool_filter), tool_filter
        elif a.startswith("reps="):
            n_reps = int(a.split("=", 1)[1])
        else:
            rest.append(a)
    only = set(rest) or None
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "summary.json")
    summary: list[dict[str, Any]] = []
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
    done = {(s["id"], s["tool"], s.get("rep", 1))
            for s in summary if s.get("rc") == 0}

    questions = load_questions()
    for q in questions:
        if only and q["id"] not in only:
            continue
        for rep in range(1, n_reps + 1):
            for tool in tool_filter:
                key = (q["id"], tool, rep)
                if key in done:
                    print(f"=== {q['id']} {tool} r{rep} — done, skip ===",
                          flush=True)
                    continue
                print(f"=== {q['id']} {tool} r{rep} ({q['repo']}) ===",
                      flush=True)
                cwd = None
                ephemeral = False
                try:
                    prompt, cwd, ephemeral = PREP[tool](q)
                    out_path = os.path.join(
                        out_dir, f"{q['id']}_{tool}_r{rep}.json")
                    dt, rc = run_claude(prompt, cwd, out_path,
                                        dict(os.environ))
                    s = summarize(out_path)
                    s.update({"id": q["id"], "tool": tool, "rep": rep,
                              "wall_s": round(dt, 1), "rc": rc})
                    summary = [x for x in summary
                               if not (x["id"] == q["id"]
                                       and x["tool"] == tool
                                       and x.get("rep", 1) == rep)]
                    summary.append(s)
                    with open(summary_path, "w") as f:
                        json.dump(summary, f, indent=2)
                    print(f"    done {dt:.0f}s rc={rc} "
                          f"cost=${s.get('cost_usd')} "
                          f"turns={s.get('num_turns')} "
                          f"out={s.get('output_tokens')}", flush=True)
                except subprocess.CalledProcessError as e:
                    print(f"    PREP FAILED: {e}", flush=True)
                    summary.append({"id": q["id"], "tool": tool, "rep": rep,
                                    "rc": -1, "error": str(e)})
                    with open(summary_path, "w") as f:
                        json.dump(summary, f, indent=2)
                finally:
                    if ephemeral and cwd:
                        shutil.rmtree(cwd, ignore_errors=True)
    print("\n=== final summary ===")
    for s in summary:
        print({k: s.get(k) for k in
               ("id", "tool", "rep", "rc", "cost_usd", "wall_s")})


if __name__ == "__main__":
    main()
