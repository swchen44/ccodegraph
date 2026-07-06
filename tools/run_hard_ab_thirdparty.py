#!/usr/bin/env python3
"""tools/run_hard_ab_thirdparty.py — 硬題 A/B 第三方對照:CodeGraph、cbm。

沿用 `run_hard_ab.py`/`run_hard_ab_armc.py` 的隔離手法(git archive HEAD 乾淨
複本、`--setting-sources project` 跳過使用者全域 skill)與同一組 4 題(WRQ-008/
009/013/017),但這次用**兩個第三方工具**取代 ccodegraph:

- **CodeGraph**(colbymchenry/codegraph,tree-sitter,~/.local/bin/codegraph):
  `codegraph init .` 預建索引,agent 用 callers/callees/impact/explore/node/
  query 等 CLI 子指令回答,必要時查 `.codegraph/codegraph.db`。
- **cbm**(win4r/codebase-memory-mcp-pro fork,tree-sitter,已知在 C 上
  CALLS 邊 ~99% 掛檔案而非函式——見 `~/git/cbm-vs-codegraph-bench/REPORT.md`
  第 200 節):`cli index_repository` 預建索引,agent 用 `cli query_graph`
  (openCypher)/`cli trace_path` 回答。

兩工具都是透過 CLI(Bash 工具)呼叫,不是 MCP 掛載——與 ccodegraph 的 Arm B/C
(同樣是 Bash 呼叫 `./ccodegraph.py`)測試方式對稱,不是因為工具做不到 MCP。

**這輪明確要求用 `--model claude-opus-4-8`**——與先前 ccodegraph 的 10 次
A/B/C(同樣是 Opus 4.8,1M context window 為該模型預設)保持模型一致,才能
公平比較 cost/turns 這類數字(先前一度打算改用 Sonnet 5,後改回與 ccodegraph
基準一致的 Opus 4.8)。

用法:python3 tools/run_hard_ab_thirdparty.py <out_dir> [case_id ...]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

REDIS = os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis")
WPA = os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/wpa_supplicant")
CG_BIN = os.path.expanduser("~/.local/bin/codegraph")
CBM_BIN = os.path.expanduser(
    "~/git/cbm-vs-codegraph-bench/repos/cbm-fork/build/c/codebase-memory-mcp")
MODEL = "claude-opus-4-8"

CASES = [
    {
        "id": "WRQ-008", "repo": "redis", "src": REDIS,
        "question": (
            "Trace the full call path from Redis command dispatch to the "
            "lowest-level database write for the SET command: from "
            "lookupCommand()/processCommand() through setCommand(), "
            "setGenericCommand(), down to the actual key-value write in "
            "db.c. List every named hop in order, with file and line for "
            "each."),
    },
    {
        "id": "WRQ-009", "repo": "wpa", "src": WPA,
        "question": (
            "struct wpa_driver_ops has 136 function-pointer fields. For "
            "the nl80211 driver backend (src/drivers/driver_nl80211.c, "
            "the wpa_driver_nl80211_ops struct literal), list EVERY field "
            "that is filled in, paired with the implementing function "
            "name. Do not stop partway through the struct literal."),
    },
    {
        "id": "WRQ-013", "repo": "wpa", "src": WPA,
        "question": (
            "wpa_supplicant has ~1985 `#ifdef CONFIG_*` conditional "
            "blocks. For CONFIG_SAE specifically, list every FUNCTION "
            "(not just file or line) whose compiled behavior depends on "
            "it, across the whole src/ tree. For each function, classify "
            "whether the ENTIRE function only exists under CONFIG_SAE "
            "(\"whole\"), or the function always exists but only PART of "
            "its body is conditional (\"partial\")."),
    },
    {
        "id": "WRQ-017", "repo": "redis", "src": REDIS,
        "question": (
            "In src/t_string.c, every call to createStringObject/"
            "createStringObjectFromLongLong/createStringObjectFromLongDouble/"
            "createStringObjectFromLongLongForValue allocates a fresh "
            "object. For EACH such allocation site, determine whether the "
            "object is (a) locally freed via decrRefCount within the SAME "
            "function, or (b) its ownership is transferred elsewhere "
            "(e.g., handed to the database as the new value) and "
            "therefore has no local decrRefCount. List both categories "
            "separately."),
    },
]

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
    "也可以直接 `sqlite3 .codegraph/codegraph.db` 查 nodes/edges 表"
    "(edges.metadata 的 synthesizedBy='fn-pointer-dispatch' 是函式指標合成邊,"
    "屬於過度近似的候選,需要人工覆核)。必要時可搭配少量 grep/cat 覆核可疑答案。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。不要修改任何檔案。")

CBM_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有第三方工具 cbm"
    "(codebase-memory-mcp,語意知識圖),已經建好索引。可用指令(絕對路徑 "
    "{cbm_bin},cache 目錄 {cache},專案名稱 {proj}):\n"
    "  CBM_CACHE_DIR={cache} {cbm_bin} cli query_graph "
    "'{{\"project\":\"{proj}\",\"query\":\"<openCypher>\"}}'\n"
    "      # 任意 Cypher 查詢圖,例如"
    " MATCH (a)-[:CALLS]->(b) WHERE a.name='foo' RETURN b.name\n"
    "  CBM_CACHE_DIR={cache} {cbm_bin} cli trace_path "
    "'{{\"project\":\"{proj}\",\"function_name\":\"<fn>\","
    "\"direction\":\"inbound|outbound\",\"depth\":3}}'\n"
    "節點 label:Function/Class(對應 struct)/Field/Variable(含 enum 值)/"
    "Macro/File/Module 等;注意 CALLS 邊在這個 C 專案上經常掛在檔案"
    "(Module/File 節點)而非函式節點,需要自行判斷這條邊是不是函式級。"
    "必要時可搭配少量 grep/cat 覆核可疑答案。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。不要修改任何檔案。")


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


def prep_codegraph(case: dict[str, Any], tmp: str) -> str:
    clean_copy(case["src"], tmp)
    env = {**os.environ, "CODEGRAPH_TELEMETRY": "0"}
    print("    [prep codegraph] init …", flush=True)
    subprocess.run([CG_BIN, "init", "."], cwd=tmp, env=env,
                  check=True, capture_output=True)
    return CODEGRAPH_TEMPLATE.format(question=case["question"])


def prep_cbm(case: dict[str, Any], tmp: str) -> str:
    clean_copy(case["src"], tmp)
    cache = os.path.join(tmp, ".cbm-cache")
    os.makedirs(cache, exist_ok=True)
    print("    [prep cbm] index_repository …", flush=True)
    subprocess.run([CBM_BIN, "--json", "cli", "index_repository",
                   json.dumps({"repo_path": tmp, "mode": "full"})],
                  env={**os.environ, "CBM_CACHE_DIR": cache},
                  check=True, capture_output=True)
    proj = next(f for f in os.listdir(cache) if f.endswith(".db"))[:-3]
    return CBM_TEMPLATE.format(cbm_bin=CBM_BIN, cache=cache, proj=proj,
                              question=case["question"])


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
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-ab-3p"
    only = set(sys.argv[2:]) or None
    os.makedirs(out_dir, exist_ok=True)
    summary = []
    for case in CASES:
        if only and case["id"] not in only:
            continue
        for tool in ("codegraph", "cbm"):
            print(f"=== {case['id']} tool={tool} ({case['repo']}) ===",
                 flush=True)
            tmp = tempfile.mkdtemp()
            try:
                if tool == "codegraph":
                    prompt = prep_codegraph(case, tmp)
                    env = {**os.environ, "CODEGRAPH_TELEMETRY": "0"}
                else:
                    prompt = prep_cbm(case, tmp)
                    env = dict(os.environ)
                out_path = os.path.join(out_dir, f"{case['id']}_{tool}.json")
                dt, rc = run_claude(prompt, tmp, out_path, env)
                s = summarize(out_path)
                s.update({"id": case["id"], "tool": tool,
                          "wall_s": round(dt, 1), "rc": rc})
                summary.append(s)
                print(f"    done in {dt:.0f}s rc={rc} "
                     f"cost=${s.get('cost_usd')} "
                     f"tokens_in={s.get('input_tokens')} "
                     f"tokens_out={s.get('output_tokens')} "
                     f"session_id={s.get('session_id')} "
                     f"models={s.get('model_usage_keys')}", flush=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n=== summary ===")
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
