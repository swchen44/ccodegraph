#!/usr/bin/env python3
"""lsp-skill 臂評分 — 1-slot(與 hint-probe 同協定),每 (題, rep) 一次
= 66 呼叫。rubric 與 v3-v6 一字不改;ANS_CAP=12000(v6.1 協定)。
用法:score_lspskill.py <runs_dir> <out_dir> [WRQ-XXX ...]
"""
import json
import os
import subprocess
import sys

REPO = "/Users/swchen.tw/git/ccodegraph"
HB = os.path.join(REPO, "docs/research/hard-benchmark")
QUESTIONS = os.path.join(HB, "questions.jsonl")
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "score_schema_1slot.json")
ANS_CAP = 12000


def gt_text(qid):
    p = os.path.join(HB, f"gt_{qid}.md")
    if not os.path.exists(p):
        return "(無獨立 GT 檔;以 evaluation_notes 為準)"
    with open(p) as f:
        return f.read()


def main():
    runs_dir, out_dir = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3:]) or None
    os.makedirs(out_dir, exist_ok=True)
    with open(QUESTIONS) as f:
        questions = [json.loads(line) for line in f if line.strip()]
    for q in questions:
        qid = q["id"]
        if only and qid not in only:
            continue
        for rep in (1, 2, 3):
            out_path = os.path.join(out_dir, f"{qid}_r{rep}.json")
            if os.path.exists(out_path):
                print(f"=== {qid} r{rep} scored, skip ===", flush=True)
                continue
            ans_path = os.path.join(runs_dir, f"{qid}_lspskill_r{rep}.json")
            if not os.path.exists(ans_path):
                print(f"=== {qid} r{rep} 缺答案,跳過 ===", flush=True)
                continue
            with open(ans_path) as f:
                ans = json.load(f).get("result", "(no result)")
            prompt = f"""You are an independent grader for a C-codebase code-navigation
benchmark (repos: wpa_supplicant / redis). Grade strictly from the evidence
below; be skeptical of confident-sounding but unverifiable claims.

## Question ({qid})
{q['question']}

## Evaluation notes (verified GT summary, includes scoring guidance)
{q.get('evaluation_notes', '')}

## Full GT reference document
{gt_text(qid)[:7000]}

## One AI agent answered this question. Score it 0-3 against the GT above:
## 0 = wrong/fabricated, 1 = mostly wrong or badly incomplete, 2 = mostly
## correct but with a real gap the GT calls out as a scoring dimension,
## 3 = fully correct per the GT's own scoring rubric.
## Give a one-to-two sentence justification, citing what matched or didn't
## match the GT.

### Answer (tool="lsp")
{ans[:ANS_CAP]}

Return JSON with key "lsp"."""
            print(f"=== scoring {qid} r{rep} ===", flush=True)
            r = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check", "--sandbox",
                 "read-only", "--output-schema", SCHEMA,
                 "--output-last-message", out_path, prompt],
                cwd=REPO, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                print(f"    FAILED rc={r.returncode}: {r.stderr[:200]}",
                      flush=True)
                continue
            with open(out_path) as f:
                print("    lsp-skill =", json.load(f)["lsp"]["score"],
                      flush=True)


if __name__ == "__main__":
    main()
