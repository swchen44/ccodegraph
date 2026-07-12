#!/usr/bin/env python3
"""v6 分析:分數矩陣(每題每臂 3 reps + 中位數)、總分、每分成本、
跨 rep 變異、LSP 工具使用率(從 transcript 統計)。"""
import glob
import json
import os
import statistics as st

RUNS = os.path.expanduser("~/kernel-bench/v6-lsp/v6-runs")
SCORES = os.path.expanduser("~/kernel-bench/v6-lsp/v6-scores")
ARMS = ("none", "ccodegraph", "lsp")
QIDS = [f"WRQ-{i:03d}" for i in range(1, 23)]


def load_scores():
    m = {}   # (qid, rep) -> {arm: (score, justification)}
    for p in glob.glob(f"{SCORES}/*.json"):
        base = os.path.basename(p)[:-5]
        qid, rep = base.rsplit("_r", 1)
        d = json.load(open(p))
        m[(qid, int(rep))] = {a: (d[a]["score"], d[a]["justification"])
                              for a in ARMS}
    return m


def main():
    scores = load_scores()
    summary = {(x["id"], x["tool"], x.get("rep", 1)): x
               for x in json.load(open(f"{RUNS}/summary.json"))
               if x.get("rc") == 0}

    print("## 分數矩陣(每格 = r1/r2/r3 → 中位)")
    totals = {a: 0 for a in ARMS}
    var_flags = []
    header = f"{'qid':9s}" + "".join(f"{a:>18s}" for a in ARMS)
    print(header)
    for qid in QIDS:
        row = f"{qid:9s}"
        for a in ARMS:
            reps = [scores.get((qid, r), {}).get(a, (None,))[0]
                    for r in (1, 2, 3)]
            if None in reps:
                row += f"{'?':>18s}"
                continue
            med = int(st.median(reps))
            totals[a] += med
            if max(reps) - min(reps) >= 2:
                var_flags.append((qid, a, reps))
            row += f"{'/'.join(map(str, reps)) + ' → ' + str(med):>18s}"
        print(row)
    print(f"\n## 總分(中位數加總,滿分 66)")
    for a in ARMS:
        cost = sum(summary[(q, a, r)]["cost_usd"]
                   for q in QIDS for r in (1, 2, 3)
                   if (q, a, r) in summary)
        cpp = cost / totals[a] if totals[a] else 0
        print(f"  {a:11s} {totals[a]}/66  總成本 ${cost:.2f}"
              f"  每分成本 ${cpp:.3f}(3 reps 合計)")
    print(f"\n## 跨 rep 變異 ≥2 分的組(N=3 穩定性)")
    if not var_flags:
        print("  無")
    for qid, a, reps in var_flags:
        print(f"  {qid} {a}: {reps}")

    # LSP 工具使用率
    print("\n## LSP 臂工具使用(66 runs transcript 統計)")
    tool_totals = {}
    op_totals = {}
    lsp_zero = []
    for qid in QIDS:
        for rep in (1, 2, 3):
            key = (qid, "lsp", rep)
            if key not in summary:
                continue
            sid = summary[key]["session_id"]
            repo = "wpa" if any(
                x["id"] == qid and x.get("repo") == "wpa"
                for x in []) else None
            hits = glob.glob(os.path.expanduser(
                f"~/.claude/projects/-Users-swchen-tw-kernel-bench-"
                f"v6-lsp-work-lsp-*/{sid}.jsonl"))
            if not hits:
                continue
            n_lsp = 0
            for line in open(hits[0]):
                if '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for c in (d.get("message", {}).get("content") or []):
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        nm = c["name"]
                        tool_totals[nm] = tool_totals.get(nm, 0) + 1
                        if nm == "LSP":
                            n_lsp += 1
                            op = c["input"].get("operation")
                            op_totals[op] = op_totals.get(op, 0) + 1
            if n_lsp == 0:
                lsp_zero.append(f"{qid}_r{rep}")
    print("  工具呼叫合計:", dict(sorted(tool_totals.items(),
                                    key=lambda x: -x[1])))
    print("  LSP 操作分布:", dict(sorted(op_totals.items(),
                                    key=lambda x: -x[1])))
    print(f"  完全沒用 LSP 的 run:{len(lsp_zero)}",
          lsp_zero[:10] if lsp_zero else "")


if __name__ == "__main__":
    main()
