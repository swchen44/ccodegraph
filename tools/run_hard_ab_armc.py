#!/usr/bin/env python3
"""tools/run_hard_ab_armc.py — Arm C:redis 真實 compile_commands.json 對照。

跟 Arm B(`run_hard_ab.py`)完全一樣的隔離/prompt 方式,唯一差異:build 前
把真實、bear 產生的 `compile_commands.json`(357 entries,含正確 -D/-I)
複製進乾淨複本的 repo 根目錄,讓 clink-import 走「compile-DB(root)」
路徑(confidence 0.95),而不是 Arm B 原本用的合成 fallback(0.93)。
只跑 redis 的 WRQ-008/WRQ-017(使用者已選定範圍:「先只做 redis 的 2 題」),
wpa 沒有真實 build 產物,故不在此列。
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

REDIS = os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis")
REAL_COMPDB = os.path.join(REDIS, "compile_commands.json")

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

ARM_C_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有 ./ccodegraph.py 這個程式碼知識圖"
    "工具,圖已經建好在 .ccodegraph/(使用真實 compile_commands.json,非合成)。"
    "請用它來回答,必要時可以搭配它的 sql 逃生口或少量 grep 覆核可疑答案。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")


def clean_copy(src: str, dst: str) -> None:
    r = subprocess.run(f"git archive HEAD | tar -x -C {dst!r}",
                       shell=True, cwd=src, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: git archive failed for {src}: {r.stderr}")


def run_claude(prompt: str, cwd: str, out_path: str,
              budget: float = 3.0) -> tuple[float, int]:
    cmd = ["claude", "-p", prompt, "--setting-sources", "project",
          "--output-format", "json", "--permission-mode", "bypassPermissions",
          "--max-budget-usd", str(budget)]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                      timeout=1200)
    dt = time.time() - t0
    with open(out_path, "w") as f:
        f.write(r.stdout)
    if r.returncode != 0:
        with open(out_path + ".stderr", "w") as f:
            f.write(r.stderr)
    return dt, r.returncode


def prep_arm_c(case: dict[str, Any], tmp: str) -> str:
    clean_copy(case["src"], tmp)
    shutil.copy(CCODEGRAPH_PY, tmp)
    shutil.copy(REAL_COMPDB, os.path.join(tmp, "compile_commands.json"))
    os.makedirs(os.path.join(tmp, ".claude", "skills", "ccodegraph"),
               exist_ok=True)
    shutil.copy(SKILL_MD,
               os.path.join(tmp, ".claude", "skills", "ccodegraph",
                            "SKILL.md"))
    print("    [prep C] build …", flush=True)
    subprocess.run(["python3", "ccodegraph.py", "build", "-p", ".", "-j", "8"],
                  cwd=tmp, check=True, capture_output=True)
    mode = "NO_CLINK_BIN"
    if os.path.exists(CLINK_BIN):
        print("    [prep C] clink-import …", flush=True)
        env = {**os.environ, "CCODEGRAPH_CLINK_PATH": CLINK_BIN}
        subprocess.run(["python3", "ccodegraph.py", "clink-import", "-p", "."],
                      cwd=tmp, env=env, capture_output=True)
        mode_file = os.path.join(tmp, ".ccodegraph", "graph.clink_mode.txt")
        if os.path.exists(mode_file):
            with open(mode_file) as f:
                mode = f.read().strip()
    return mode


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
    }


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-ab-c"
    os.makedirs(out_dir, exist_ok=True)
    summary = []
    for case in CASES:
        print(f"=== {case['id']} arm C ({case['repo']}) ===", flush=True)
        tmp = tempfile.mkdtemp()
        try:
            mode = prep_arm_c(case, tmp)
            prompt = ARM_C_TEMPLATE.format(question=case["question"])
            out_path = os.path.join(out_dir, f"{case['id']}_C.json")
            dt, rc = run_claude(prompt, tmp, out_path)
            s = summarize(out_path)
            s.update({"id": case["id"], "arm": "C", "wall_s": round(dt, 1),
                      "rc": rc, "compdb_mode": mode})
            summary.append(s)
            print(f"    done in {dt:.0f}s rc={rc} mode={mode} "
                 f"cost=${s.get('cost_usd')} "
                 f"tokens_in={s.get('input_tokens')} "
                 f"tokens_out={s.get('output_tokens')} "
                 f"session_id={s.get('session_id')}", flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n=== summary ===")
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
