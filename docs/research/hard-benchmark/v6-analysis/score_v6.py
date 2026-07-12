#!/usr/bin/env python3
"""v6 codex 評分 — 3-slot(none/ccodegraph/lsp),每 (題, rep) 一次 = 66 呼叫。
GT 沿用 v3/v4:questions.jsonl 的 evaluation_notes + gt_WRQ-XXX.md。
評分 rubric 文字與 v3/v4/v5 相同(0-3,獨立判定,引用 GT 依據)。
用法:score_v6.py <runs_dir> <out_dir> [WRQ-XXX ...]
"""
import json
import os
import subprocess
import sys

REPO = "/Users/swchen.tw/git/ccodegraph"
HB = os.path.join(REPO, "docs/research/hard-benchmark")
QUESTIONS = os.path.join(HB, "questions.jsonl")
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "score_schema.json")
ARMS = ("none", "ccodegraph", "lsp")


def gt_text(qid):
    p = os.path.join(HB, f"gt_{qid}.md")
    if not os.path.exists(p):
        return "(無獨立 GT 檔;以 evaluation_notes 為準)"
    with open(p) as f:
        return f.read()


def answer_text(runs_dir, qid, tool, rep):
    p = os.path.join(runs_dir, f"{qid}_{tool}_r{rep}.json")
    with open(p) as f:
        return json.load(f).get("result", "(no result)")


def build_prompt(q, runs_dir, rep):
    qid = q["id"]
    answers = {t: answer_text(runs_dir, qid, t, rep) for t in ARMS}
    return f"""You are an independent grader for a C-codebase code-navigation
benchmark (repos: wpa_supplicant / redis). You are NOT the one who built the
ground truth or ran the agents — grade strictly from the evidence below, and
be skeptical of confident-sounding but unverifiable claims.

## Question ({qid})
{q['question']}

## Evaluation notes (verified GT summary, includes scoring guidance)
{q.get('evaluation_notes', '')}

## Full GT reference document
{gt_text(qid)[:7000]}

## Three independent AI agents answered this question, each with a different
## tool setup. Score EACH one 0-3 against the GT above:
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

### Answer C (tool="lsp", clangd LSP via compile_commands.json)
{answers['lsp'][:4000]}

Return your scores as JSON matching the required schema, using these EXACT
keys for the three answers: "none" (Answer A), "ccodegraph" (Answer B),
"lsp" (Answer C).
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
            missing = [t for t in ARMS if not os.path.exists(
                os.path.join(runs_dir, f"{qid}_{t}_r{rep}.json"))]
            if missing:
                print(f"=== {qid} r{rep} 缺 {missing},跳過 ===", flush=True)
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
