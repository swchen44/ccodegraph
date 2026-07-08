#!/usr/bin/env python3
"""v4 codex scoring — same 4-slot prompt as v3, with the ccodegraph slot
replaced by the v4 answer; other 3 arms stay as v3 anchors. Extract only the
ccodegraph score. Usage: score_v4.py <v4_runs_dir> <out_dir> [WRQ-0XX ...]"""
import json
import os
import subprocess
import sys

REPO = "/Users/swchen.tw/git/ccodegraph"
QUESTIONS = os.path.join(REPO, "docs/research/hard-benchmark/questions.jsonl")
V3_RUNS = os.path.join(REPO, "docs/research/hard-benchmark/v3-runs")
SCHEMA = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/score_schema.json"

GT_FILE_OVERRIDE = {
    "WRQ-008": "gt_case2_set_chain.md",
    "WRQ-009": "gt_case1_driver_ops.txt",
    "WRQ-017": "gt_case4_lifecycle.md",
}


def gt_text(qid):
    fname = GT_FILE_OVERRIDE.get(qid, f"gt_{qid}.md")
    path = os.path.join(REPO, "docs/research/hard-benchmark", fname)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "(no separate GT file — see evaluation_notes)"


def answer_text(runs_dir, qid, tool):
    with open(os.path.join(runs_dir, f"{qid}_{tool}.json")) as f:
        return json.load(f).get("result", "(no result)")


def build_prompt(q, v4_dir):
    qid = q["id"]
    answers = {
        "none": answer_text(V3_RUNS, qid, "none"),
        "ccodegraph": answer_text(v4_dir, qid, "ccodegraph"),  # v4 slot
        "codegraph": answer_text(V3_RUNS, qid, "codegraph"),
        "cbm": answer_text(V3_RUNS, qid, "cbm"),
    }
    return f"""You are an independent grader for a code-navigation benchmark. You are
NOT the one who built the ground truth or ran the agents being graded — grade
strictly from the evidence given below, and be skeptical of confident-sounding
but unverifiable claims.

## Question ({qid})
{q['question']}

## Evaluation notes (from GT construction, includes scoring guidance)
{q.get('evaluation_notes', '')}

## Full GT reference document
{gt_text(qid)[:6000]}

## Four independent AI agents answered this question, each with a different
## tool/no-tool setup. Score EACH one 0-3 against the GT above:
## 0 = wrong/fabricated, 1 = mostly wrong or badly incomplete, 2 = mostly
## correct but with a real gap the GT calls out as a scoring dimension,
## 3 = fully correct per the GT's own scoring rubric.
## Judge each answer independently — do not let one answer's quality anchor
## your judgment of the others. Give a one-to-two sentence justification per
## score, citing what matched or didn't match the GT.

### Answer A (tool="none", grep/read only)
{answers['none'][:4000]}

### Answer B (tool="ccodegraph")
{answers['ccodegraph'][:4000]}

### Answer C (tool="codegraph", third-party)
{answers['codegraph'][:4000]}

### Answer D (tool="cbm", third-party)
{answers['cbm'][:4000]}

Return your scores as JSON matching the required schema, using these EXACT
keys for the four answers: "none" (Answer A), "ccodegraph" (Answer B),
"codegraph" (Answer C), "cbm" (Answer D).
"""


def main():
    v4_dir, out_dir = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3:]) or None
    os.makedirs(out_dir, exist_ok=True)
    with open(QUESTIONS) as f:
        questions = [json.loads(line) for line in f if line.strip()]
    for q in questions:
        qid = q["id"]
        if only and qid not in only:
            continue
        if not os.path.exists(os.path.join(v4_dir, f"{qid}_ccodegraph.json")):
            continue
        out_path = os.path.join(out_dir, f"{qid}.json")
        if os.path.exists(out_path):
            print(f"=== {qid} already scored, skip ===", flush=True)
            continue
        print(f"=== scoring {qid} ===", flush=True)
        r = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
             "--output-schema", SCHEMA, "--output-last-message", out_path,
             build_prompt(q, v4_dir)],
            cwd=REPO, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"    FAILED rc={r.returncode}: {r.stderr[:400]}", flush=True)
            continue
        with open(out_path) as f:
            parsed = json.load(f)
        print(f"    ccodegraph(v4): {parsed['ccodegraph']}", flush=True)


if __name__ == "__main__":
    main()
