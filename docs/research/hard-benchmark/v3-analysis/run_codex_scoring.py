#!/usr/bin/env python3
"""Independently score all 22 questions' 4 arm-answers using codex exec.

For each question: gather the GT (from the corresponding gt_WRQ-0XX.md file,
or the executed-case gt files for WRQ-008/009/013/017), the question text,
and the 4 arms' raw answer text (from the v3 run JSONs). Ask codex (a
different model/vendor, not Claude) to independently score each 0-3 with a
justification, via --output-schema for structured output.
"""
import glob
import json
import os
import subprocess
import sys

REPO = "/Users/swchen.tw/git/ccodegraph"
QUESTIONS = os.path.join(REPO, "docs/research/hard-benchmark/questions.jsonl")
V3_RUNS = os.path.join(REPO, "docs/research/hard-benchmark/v3-runs")
SCHEMA = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/score_schema.json"
OUT_DIR = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/codex-scores"
os.makedirs(OUT_DIR, exist_ok=True)

GT_FILE_OVERRIDE = {
    "WRQ-008": "gt_case2_set_chain.md",
    "WRQ-009": "gt_case1_driver_ops.txt",
    "WRQ-017": "gt_case4_lifecycle.md",
}


def load_questions():
    with open(QUESTIONS) as f:
        return [json.loads(line) for line in f if line.strip()]


def gt_text(qid):
    fname = GT_FILE_OVERRIDE.get(qid, f"gt_{qid}.md")
    path = os.path.join(REPO, "docs/research/hard-benchmark", fname)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "(no separate GT file — see evaluation_notes)"


def answer_text(qid, tool):
    path = os.path.join(V3_RUNS, f"{qid}_{tool}.json")
    with open(path) as f:
        data = json.load(f)
    return data.get("result", "(no result)")


def build_prompt(q):
    qid = q["id"]
    gt = gt_text(qid)
    notes = q.get("evaluation_notes", "")
    answers = {t: answer_text(qid, t) for t in ("none", "ccodegraph", "codegraph", "cbm")}

    prompt = f"""You are an independent grader for a code-navigation benchmark. You are
NOT the one who built the ground truth or ran the agents being graded — grade
strictly from the evidence given below, and be skeptical of confident-sounding
but unverifiable claims.

## Question ({qid})
{q['question']}

## Evaluation notes (from GT construction, includes scoring guidance)
{notes}

## Full GT reference document
{gt[:6000]}

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
    return prompt


def run_codex(prompt, out_path):
    cmd = ["codex", "exec", "--skip-git-repo-check",
          "--sandbox", "read-only",
          "--output-schema", SCHEMA,
          "--output-last-message", out_path,
          prompt]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def main():
    only = set(sys.argv[1:]) or None
    questions = load_questions()
    results = {}
    for q in questions:
        qid = q["id"]
        if only and qid not in only:
            continue
        out_path = os.path.join(OUT_DIR, f"{qid}.json")
        if os.path.exists(out_path):
            print(f"=== {qid} already scored, skip ===", flush=True)
            continue
        print(f"=== scoring {qid} ===", flush=True)
        prompt = build_prompt(q)
        rc, out, err = run_codex(prompt, out_path)
        if rc != 0:
            print(f"    FAILED rc={rc}: {err[:500]}", flush=True)
            continue
        try:
            with open(out_path) as f:
                parsed = json.load(f)
            print(f"    ok: {parsed}", flush=True)
        except Exception as e:
            print(f"    output parse issue: {e}; raw stdout tail: {out[-500:]}",
                 flush=True)


if __name__ == "__main__":
    main()
