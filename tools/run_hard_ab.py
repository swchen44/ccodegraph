#!/usr/bin/env python3
"""tools/run_hard_ab.py — R4a v2 硬題 A/B harness(headless Claude Code)。

Isolation(2026-07-06 已驗證):`claude -p --setting-sources project` 只讀專案層
設定,完全跳過 `~/.claude/skills/ccq`(全域符號連結)。Arm A 拿到乾淨複本(無
skill、無 ccodegraph);Arm B 拿到複本 + ccodegraph.py + 預先建好的圖 +
專案層 `.claude/skills/ccodegraph/SKILL.md`。兩臂互不干擾、不碰使用者全域設定。

用法:python3 tools/run_hard_ab.py <out_dir> [case_id ...]
不帶 case_id 跑全部 4 題;帶 id(如 WRQ-008)只跑指定題,方便單題先驗證。
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

WPA = os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/wpa_supplicant")
REDIS = os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis")

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

ARM_A_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。只能用 shell 指令(grep/awk/sed/cat/"
    "find/Read)探索原始碼,不要安裝或呼叫任何額外工具,也不要嘗試連網。"
    "任務:{question} 回答精簡但完整,不要省略你找到的細節列表。"
    "不要修改任何檔案。")

ARM_B_TEMPLATE = (
    "你在一個 C 專案 repo(唯讀複本)。這裡有 ./ccodegraph.py 這個程式碼知識圖"
    "工具,圖已經建好在 .ccodegraph/。請用它來回答,必要時可以搭配它的 sql "
    "逃生口或少量 grep 覆核可疑答案。任務:{question} 回答精簡但完整,"
    "不要省略你找到的細節列表。不要修改任何檔案。")


def clean_copy(src: str, dst: str) -> None:
    """git archive HEAD 只取已提交、乾淨的檔案——排除本 session 在這些真實 repo
    上留下的所有實驗產物(.ccodegraph/、.cscope-graph.db、cscope.out 等),
    不必窮舉檔名(這條路本來就該用,先前用 ignore_patterns 猜檔名漏了東西,
    是這次驗證階段抓到的真問題)。"""
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


def prep_arm_a(case: dict[str, Any], tmp: str) -> None:
    clean_copy(case["src"], tmp)


def prep_arm_b(case: dict[str, Any], tmp: str) -> None:
    clean_copy(case["src"], tmp)
    shutil.copy(CCODEGRAPH_PY, tmp)
    os.makedirs(os.path.join(tmp, ".claude", "skills", "ccodegraph"),
               exist_ok=True)
    shutil.copy(SKILL_MD,
               os.path.join(tmp, ".claude", "skills", "ccodegraph",
                            "SKILL.md"))
    print("    [prep B] build …", flush=True)
    subprocess.run(["python3", "ccodegraph.py", "build", "-p", ".", "-j", "8"],
                  cwd=tmp, check=True, capture_output=True)
    if os.path.exists(CLINK_BIN):
        print("    [prep B] clink-import …", flush=True)
        env = {**os.environ, "CCODEGRAPH_CLINK_PATH": CLINK_BIN}
        subprocess.run(["python3", "ccodegraph.py", "clink-import", "-p", "."],
                      cwd=tmp, env=env, capture_output=True)


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
    }


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-ab"
    only = set(sys.argv[2:]) or None
    os.makedirs(out_dir, exist_ok=True)
    summary = []
    for case in CASES:
        if only and case["id"] not in only:
            continue
        for arm in ("A", "B"):
            print(f"=== {case['id']} arm {arm} ({case['repo']}) ===",
                 flush=True)
            tmp = tempfile.mkdtemp()
            try:
                if arm == "A":
                    prep_arm_a(case, tmp)
                    prompt = ARM_A_TEMPLATE.format(question=case["question"])
                else:
                    prep_arm_b(case, tmp)
                    prompt = ARM_B_TEMPLATE.format(question=case["question"])
                out_path = os.path.join(out_dir, f"{case['id']}_{arm}.json")
                dt, rc = run_claude(prompt, tmp, out_path)
                s = summarize(out_path)
                s.update({"id": case["id"], "arm": arm, "wall_s": round(dt, 1),
                          "rc": rc})
                summary.append(s)
                print(f"    done in {dt:.0f}s rc={rc} "
                     f"cost=${s.get('cost_usd')} "
                     f"tokens_in={s.get('input_tokens')} "
                     f"tokens_out={s.get('output_tokens')}", flush=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n=== summary ===")
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
