#!/usr/bin/env python3
"""Aggregate the raw per-run tool-call data into token-hotspot summaries."""
import json
from collections import defaultdict

with open("/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/analysis_raw.json") as f:
    data = json.load(f)["results"]

TOOLS = ("none", "ccodegraph", "codegraph", "cbm")

# 1) per-arm overall stats
print("=" * 70)
print("PER-ARM OVERALL (across all 22 questions)")
print("=" * 70)
for tool in TOOLS:
    runs = [r for r in data if r["tool"] == tool]
    n = len(runs)
    cost = sum(r["cost_usd"] or 0 for r in runs)
    inp = sum(r["input_tokens"] or 0 for r in runs)
    out = sum(r["output_tokens"] or 0 for r in runs)
    cread = sum(r["cache_read"] or 0 for r in runs)
    ccreate = sum(r["cache_creation"] or 0 for r in runs)
    turns = sum(r["num_turns"] or 0 for r in runs)
    calls = sum(len(r["calls"]) for r in runs)
    result_bytes = sum(sum(c["result_bytes"] for c in r["calls"]) for r in runs)
    print(f"{tool:12s} n={n:3d} cost=${cost:7.2f} turns={turns:4d} "
         f"bash+read_calls={calls:4d} "
         f"cache_read={cread:9d} cache_create={ccreate:8d} "
         f"in={inp:6d} out={out:7d} "
         f"tool_result_bytes={result_bytes:9d}")

print()
print("=" * 70)
print("PER-ARM: tool_result bytes by command signature (top contributors)")
print("=" * 70)
for tool in TOOLS:
    runs = [r for r in data if r["tool"] == tool]
    by_sig = defaultdict(lambda: [0, 0])  # [count, total_bytes]
    for r in runs:
        for c in r["calls"]:
            by_sig[c["sig"]][0] += 1
            by_sig[c["sig"]][1] += c["result_bytes"]
    print(f"\n--- {tool} ---")
    for sig, (cnt, tb) in sorted(by_sig.items(), key=lambda kv: -kv[1][1])[:12]:
        avg = tb / cnt if cnt else 0
        print(f"  {sig:28s} calls={cnt:4d} total_bytes={tb:9d} avg_bytes={avg:8.0f}")

print()
print("=" * 70)
print("PER-QUESTION: cost by arm (for the report table)")
print("=" * 70)
qids = sorted(set(r["id"] for r in data),
             key=lambda x: int(x.split("-")[1]))
for qid in qids:
    row = {}
    for tool in TOOLS:
        match = [r for r in data if r["id"] == qid and r["tool"] == tool]
        if match:
            r = match[0]
            row[tool] = (r["cost_usd"], r["num_turns"], len(r["calls"]))
    print(qid, row)
