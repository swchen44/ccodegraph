#!/usr/bin/env python3
"""v5 codex scoring — same 4-slot protocol as v3/v4, applied per (question, rep).
GT = gt_LKQ-XXX.md + jsonl evaluation_notes. 20 questions x 3 reps = 60 calls.
Usage: score_v5.py <runs_dir> <out_dir> [LKQ-XXX ...]"""
import json
import os
import subprocess
import sys

REPO = "/Users/swchen.tw/git/ccodegraph"
KDIR = os.path.join(REPO, "docs/research/hard-benchmark/kernel")
QUESTIONS = os.path.join(KDIR, "questions-kernel.jsonl")
SCHEMA = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/score_schema.json"


ANS_CAP = 12000   # v6.1 協定修正回灌:4000 會截斷長清單答案誤導評分者


def gt_text(qid):
    with open(os.path.join(KDIR, f"gt_{qid}.md")) as f:
        text = f.read()
    # SUBTREE ADDENDUM 常在檔尾,截斷會把它切掉(LKQ-006 曾因此被誤評)——
    # 把 addendum 抽出並前置,保證進 prompt。
    marker = "## SUBTREE ADDENDUM"
    if marker in text:
        idx = text.index(marker)
        text = text[idx:] + "\n\n---\n\n" + text[:idx]
    return text


def answer_text(runs_dir, qid, tool, rep):
    with open(os.path.join(runs_dir, f"{qid}_{tool}_r{rep}.json")) as f:
        return json.load(f).get("result", "(no result)")


def build_prompt(q, runs_dir, rep):
    qid = q["id"]
    answers = {t: answer_text(runs_dir, qid, t, rep)
               for t in ("none", "ccodegraph", "codegraph", "cbm")}
    return f"""You are an independent grader for a Linux-kernel (v6.6) code-navigation
benchmark. You are NOT the one who built the ground truth or ran the agents —
grade strictly from the evidence below, and be skeptical of confident-sounding
but unverifiable claims. NOTE: the execution tree was an 8,170-file subtree of
v6.6; the GT documents include SUBTREE ADDENDUM sections where tree-scoped
facts differ — honor those addenda over full-tree statements when they exist.

## Question ({qid})
{q['question']}

## Evaluation notes (verified GT summary, includes scoring guidance)
{q.get('evaluation_notes', '')}

## Full GT reference document
{gt_text(qid)[:7000]}

## Four independent AI agents answered this question, each with a different
## tool/no-tool setup. Score EACH one 0-3 against the GT above:
## 0 = wrong/fabricated, 1 = mostly wrong or badly incomplete, 2 = mostly
## correct but with a real gap the GT calls out as a scoring dimension,
## 3 = fully correct per the GT's own scoring rubric.
## Judge each answer independently — do not let one answer's quality anchor
## your judgment of the others. Give a one-to-two sentence justification per
## score, citing what matched or didn't match the GT.

### Answer A (tool="none", grep/read only)
{answers['none'][:ANS_CAP]}

### Answer B (tool="ccodegraph")
{answers['ccodegraph'][:ANS_CAP]}

### Answer C (tool="codegraph", third-party)
{answers['codegraph'][:ANS_CAP]}

### Answer D (tool="cbm", third-party)
{answers['cbm'][:ANS_CAP]}

Return your scores as JSON matching the required schema, using these EXACT
keys for the four answers: "none" (Answer A), "ccodegraph" (Answer B),
"codegraph" (Answer C), "cbm" (Answer D).
"""


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
            print(f"=== scoring {qid} r{rep} ===", flush=True)
            r = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check", "--sandbox",
                 "read-only", "--output-schema", SCHEMA,
                 "--output-last-message", out_path,
                 build_prompt(q, runs_dir, rep)],
                cwd=REPO, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                print(f"    FAILED rc={r.returncode}: {r.stderr[:300]}",
                      flush=True)
                continue
            with open(out_path) as f:
                parsed = json.load(f)
            print("    " + " ".join(f"{t}={parsed[t]['score']}"
                                    for t in parsed), flush=True)


if __name__ == "__main__":
    main()
