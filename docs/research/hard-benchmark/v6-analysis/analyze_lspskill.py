#!/usr/bin/env python3
"""lsp-skill 臂最終分析:四臂逐題中位數對照、總分、跨 rep 變異、
LSP/Skill 使用率遙測(增補 2 的數字全部由此腳本產出)。
用法:analyze_lspskill.py <skill_runs> <skill_scores> <v6_scores>
transcript 統計需在原機執行(讀 ~/.claude/projects/ 的 session jsonl)。
"""
import glob
import json
import os
import statistics as st
import sys

QIDS = [f"WRQ-{i:03d}" for i in range(1, 23)]
ARMS = ("none", "ccodegraph", "lsp")


def main() -> None:
    skill_runs, skill_scores, v6_scores = sys.argv[1:4]
    sk = {}
    for p in glob.glob(f"{skill_scores}/WRQ-*.json"):
        base = os.path.basename(p)[:-5]
        qid, rep = base.rsplit("_r", 1)
        with open(p) as f:
            sk[(qid, int(rep))] = json.load(f)["lsp"]["score"]
    v6 = {}
    for p in glob.glob(f"{v6_scores}/WRQ-*.json"):
        if p.endswith(".pre-v61"):
            continue
        base = os.path.basename(p)[:-5]
        qid, rep = base.rsplit("_r", 1)
        with open(p) as f:
            d = json.load(f)
            v6[(qid, int(rep))] = {a: d[a]["score"] for a in ARMS}

    tot_sk = 0
    tots = dict.fromkeys(ARMS, 0)
    var_flags = []
    print(f"{'qid':9s}{'none':>6s}{'ccg':>6s}{'lsp':>6s}{'lsp-skill':>14s}")
    for qid in QIDS:
        meds = {}
        for a in ARMS:
            reps = [v6[(qid, r)][a] for r in (1, 2, 3)]
            meds[a] = int(st.median(reps))
            tots[a] += meds[a]
        reps_sk = [sk[(qid, r)] for r in (1, 2, 3)]
        med_sk = int(st.median(reps_sk))
        tot_sk += med_sk
        if max(reps_sk) - min(reps_sk) >= 2:
            var_flags.append((qid, reps_sk))
        mark = " ◄" if med_sk != meds["lsp"] else ""
        print(f"{qid:9s}{meds['none']:>6d}{meds['ccodegraph']:>6d}"
              f"{meds['lsp']:>6d}"
              f"{'/'.join(map(str, reps_sk)) + '→' + str(med_sk):>14s}{mark}")
    print(f"\n總分/66: none {tots['none']} | ccodegraph {tots['ccodegraph']}"
          f" | lsp {tots['lsp']} | lsp-skill {tot_sk}")
    with open(f"{skill_runs}/summary.json") as f:
        runs = [x for x in json.load(f) if x.get("rc") == 0]
    cost = sum(x["cost_usd"] for x in runs)
    print(f"lsp-skill: {len(runs)} runs 總成本 ${cost:.2f}"
          f" 每分 ${cost / tot_sk:.3f}"
          f" wall中位 {st.median([x['wall_s'] for x in runs]):.0f}s")
    print("跨 rep 變異≥2:", var_flags if var_flags else "無")

    # 使用率遙測(原機限定)
    tool_tot: dict[str, int] = {}
    op_tot: dict[str, int] = {}
    zero = skill_inv = seen = 0
    for x in runs:
        sid = x["session_id"]
        hits = glob.glob(os.path.expanduser(
            "~/.claude/projects/-Users-swchen-tw-kernel-bench-"
            f"v6-lsp-work-lspskill-*/{sid}.jsonl"))
        if not hits:
            continue
        seen += 1
        n_lsp = 0
        inv = False
        with open(hits[0]) as fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for c in (d.get("message", {}).get("content") or []):
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        nm = c["name"]
                        tool_tot[nm] = tool_tot.get(nm, 0) + 1
                        if nm == "LSP":
                            n_lsp += 1
                            op = c["input"].get("operation")
                            op_tot[op] = op_tot.get(op, 0) + 1
                        elif nm == "Skill" and "lsp" in str(
                                c["input"].get("skill", "")):
                            inv = True
        if n_lsp == 0:
            zero += 1
        if inv:
            skill_inv += 1
    if seen:
        print(f"\nskill 觸發 {skill_inv}/{seen};零 LSP runs {zero}/{seen}")
        print("工具合計:", dict(sorted(tool_tot.items(),
                                    key=lambda kv: -kv[1])))
        print("LSP 操作:", dict(sorted(op_tot.items(),
                                    key=lambda kv: -kv[1])))
    else:
        print("\n(transcript 不在本機,使用率遙測跳過)")


if __name__ == "__main__":
    main()
