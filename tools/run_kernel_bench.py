#!/usr/bin/env python3
"""tools/run_kernel_bench.py — v5:Linux kernel(v6.6 全樹)四工具對決。

與 v3/v4(wpa/redis)的差異:
- 題庫:docs/research/hard-benchmark/kernel/questions-kernel.jsonl(20 題)。
- **N=3**:summary key = (qid, tool, rep);執行順序 題→rep→臂(臂最內圈),
  讓同一 rep 的四臂在時間上相鄰,公平分攤 API 延遲漂移。
- **計時是頭條**:嚴格循序(絕不平行);wall_s(time.time() 包 subprocess)+
  claude 回報的 duration_ms 與 duration_api_ms 全部入檔。
- **索引重用**:kernel 級索引太貴,不能每 run 重建。Stage 1 在固定工作目錄
  (路徑固定——cbm 的 project key 依路徑導出、ccodegraph graph 記錄 root)
  建一次;每 run 前做廉價完整性檢查(檔案數 + 固定抽樣檔案的 mtime),
  髒了才整樹重解 + 搬回索引。prompt 一律要求唯讀,v2-v4 兩百多次執行
  從未觀察到修改,檢查是保險絲不是常態路徑。
- **no-build**:ccodegraph 用合成 compile DB(無 compile_commands.json、
  不跑 clink);不執行 make defconfig;cbm/codegraph 本來就 zero-build。

Prompt 模板與 v3/v4 一字不差(跨輪可比)。
用法:python3 tools/run_kernel_bench.py <out_dir> [tools=a,b] [reps=N] [LKQ-0XX ...]
"""
import json
import os
import subprocess
import sys
import time
from typing import Any

CCODEGRAPH_REPO = os.path.expanduser("~/git/ccodegraph")
QUESTIONS_JSONL = os.path.join(
    CCODEGRAPH_REPO, "docs/research/hard-benchmark/kernel/questions-kernel.jsonl")
KERNEL_TAR = os.path.expanduser("~/kernel-bench/kernel-subtree.tar")
# v5 執行樹 = 8,170 檔子樹(全樹三工具索引皆 DNF;子樹涵蓋全部 20 題範圍,
# 樹域 GT 事實已重驗——見 gt_LKQ-001/006/035/060 的 SUBTREE ADDENDUM)
WORK_BASE = os.path.expanduser("~/kernel-bench")

CG_BIN = os.path.expanduser("~/.local/bin/codegraph")
CBM_BIN = os.path.expanduser(
    "~/git/cbm-vs-codegraph-bench/repos/cbm-fork/build/c/codebase-memory-mcp")
CBM_CACHE = os.path.join(WORK_BASE, "cbm-cache")   # 樹外固定路徑(重解樹不毀 cache)
MODEL = "claude-sonnet-5"
TOOLS = ("none", "ccodegraph", "codegraph", "cbm")
REPS = 3

# 完整性檢查抽樣(固定樣本,涵蓋各子系統;mtime 或缺檔即視為髒)
SENTINELS = ["kernel/fork.c", "fs/read_write.c", "net/core/dev.c",
             "include/linux/sched.h", "drivers/net/ethernet/intel/e1000e/netdev.c",
             "kernel/sched/core.c", "drivers/char/mem.c", "MAINTAINERS"]

NONE_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。只能用 shell 指令(grep/awk/sed/cat/find/"
    "Read)探索原始碼,不要安裝或呼叫任何額外工具,也不要嘗試連網。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")

CCODEGRAPH_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有 ./ccodegraph.py 這個程式碼知識圖"
    "工具,圖已經建好在 .ccodegraph/。請用它來回答,必要時可以搭配它的 sql "
    "逃生口或少量 grep 覆核可疑答案。任務:{question} 回答精簡但完整,"
    "不要省略你找到的細節列表。不要修改任何檔案。")

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


def workdir(tool: str) -> str:
    return os.path.join(WORK_BASE, f"work-{tool}")


INDEX_DIRS = {"ccodegraph": ".ccodegraph", "codegraph": ".codegraph"}


def fingerprint(wd: str) -> dict[str, Any] | None:
    fp: dict[str, Any] = {}
    for s in SENTINELS:
        p = os.path.join(wd, s)
        if not os.path.exists(p):
            return None
        st = os.stat(p)
        fp[s] = (st.st_mtime_ns, st.st_size)
    return fp


def extract_tree(tool: str) -> None:
    """整樹重解到固定路徑;保留該臂的索引目錄(先搬出、解後搬回)。"""
    wd = workdir(tool)
    keep = INDEX_DIRS.get(tool)
    stash = None
    if keep and os.path.isdir(os.path.join(wd, keep)):
        stash = os.path.join(WORK_BASE, f"stash-{tool}")
        subprocess.run(["mv", os.path.join(wd, keep), stash], check=True)
    subprocess.run(["rm", "-rf", wd], check=True)
    os.makedirs(wd)
    r = subprocess.run(["tar", "-xf", KERNEL_TAR, "-C", wd],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: subtree tar extract failed: {r.stderr}")
    if stash:
        assert keep is not None  # stash 只在 keep 為真時建立
        subprocess.run(["mv", stash, os.path.join(wd, keep)], check=True)
    # ccodegraph 臂需要工具本體與專案層 skill
    if tool == "ccodegraph":
        subprocess.run(["cp", os.path.join(CCODEGRAPH_REPO, "ccodegraph.py"), wd],
                       check=True)
        skdir = os.path.join(wd, ".claude", "skills", "ccodegraph")
        os.makedirs(skdir, exist_ok=True)
        subprocess.run(["cp", os.path.join(CCODEGRAPH_REPO,
                                           "skills/ccodegraph/SKILL.md"), skdir],
                       check=True)


def ensure_clean(tool: str, baselines: dict[str, Any]) -> None:
    wd = workdir(tool)
    fp = fingerprint(wd)
    if fp is None or (tool in baselines and fp != baselines[tool]):
        print(f"    [{tool}] tree dirty/missing — re-extracting", flush=True)
        extract_tree(tool)
        fp = fingerprint(wd)
        assert fp is not None, f"sentinels missing after extract in {wd}"
    baselines[tool] = fp


def cbm_project() -> str:
    cands = [f for f in os.listdir(CBM_CACHE) if f.endswith(".db")]
    assert len(cands) == 1, f"expected exactly 1 cbm db, got {cands}"
    return cands[0][:-3]


def build_prompt(tool: str, question: str) -> str:
    if tool == "none":
        return NONE_TEMPLATE.format(question=question)
    if tool == "ccodegraph":
        return CCODEGRAPH_TEMPLATE.format(question=question)
    if tool == "codegraph":
        return CODEGRAPH_TEMPLATE.format(question=question)
    return CBM_TEMPLATE.format(cbm_bin=CBM_BIN, cache=CBM_CACHE,
                               proj=cbm_project(), question=question)


def run_claude(prompt: str, cwd: str, out_path: str,
               budget: float = 3.0) -> tuple[float, int]:
    cmd = ["claude", "-p", prompt, "--setting-sources", "project",
           "--output-format", "json", "--permission-mode", "bypassPermissions",
           "--model", MODEL, "--max-budget-usd", str(budget)]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       timeout=1800)
    dt = time.time() - t0
    with open(out_path, "w") as f:
        f.write(r.stdout)
    if r.returncode != 0:
        with open(out_path + ".stderr", "w") as f:
            f.write(r.stderr)
    return dt, r.returncode


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
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kernel-bench-runs"
    tool_filter: tuple[str, ...] = TOOLS
    reps = REPS
    only: set[str] = set()
    for argv_item in sys.argv[2:]:
        if argv_item.startswith("tools="):
            tool_filter = tuple(argv_item.split("=", 1)[1].split(","))
            assert all(t in TOOLS for t in tool_filter), tool_filter
        elif argv_item.startswith("reps="):
            reps = int(argv_item.split("=", 1)[1])
        else:
            only.add(argv_item)
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "summary.json")
    summary: list[dict[str, Any]] = []
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
    done = {(s["id"], s["tool"], s["rep"]) for s in summary if s.get("rc") == 0}
    baselines: dict[str, Any] = {}

    for q in load_questions():
        if only and q["id"] not in only:
            continue
        for rep in range(1, reps + 1):
            for tool in tool_filter:
                key = (q["id"], tool, rep)
                if key in done:
                    print(f"=== {q['id']} {tool} rep{rep} — done, skip ===",
                          flush=True)
                    continue
                print(f"=== {q['id']} tool={tool} rep={rep} ===", flush=True)
                ensure_clean(tool, baselines)
                prompt = build_prompt(tool, q["question"])
                out_path = os.path.join(out_dir,
                                        f"{q['id']}_{tool}_r{rep}.json")
                try:
                    dt, rc = run_claude(prompt, workdir(tool), out_path)
                except subprocess.TimeoutExpired:
                    print("    TIMEOUT 1800s", flush=True)
                    summary.append({"id": q["id"], "tool": tool, "rep": rep,
                                    "rc": -9, "error": "timeout"})
                    with open(summary_path, "w") as f:
                        json.dump(summary, f, indent=2)
                    continue
                s = summarize(out_path)
                s.update({"id": q["id"], "tool": tool, "rep": rep,
                          "wall_s": round(dt, 1), "rc": rc})
                summary = [x for x in summary
                           if not (x["id"] == q["id"] and x["tool"] == tool
                                   and x.get("rep") == rep)]
                summary.append(s)
                with open(summary_path, "w") as f:
                    json.dump(summary, f, indent=2)
                print(f"    done {dt:.0f}s rc={rc} cost=${s.get('cost_usd')} "
                      f"api_ms={s.get('duration_api_ms')} "
                      f"models={s.get('model_usage_keys')}", flush=True)
    print("\n=== final: ", len(summary), "entries ===")


if __name__ == "__main__":
    main()
