#!/usr/bin/env python3
"""v6 診斷探針:在 LSP prompt 加「使用時機」提示,對三題重跑 x3。
WRQ-009(fnptr,基線 2/2/2、LSP 使用 0 次)與 WRQ-019(基線 1/2/2、
r1/r2 未用 LSP)= 提示應有效區;WRQ-016(includes 計數,LSP 無此原語)
= 負對照(提示不該救得了缺原語的題)。輸出到獨立目錄,不污染 v6 正式數據。
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/git/ccodegraph/tools"))

import run_hard_ab_v6 as h

HINT = (
    "使用時機提示:『誰呼叫 X / 誰實作這個介面 / 這個函式指標欄位接到哪些"
    "函式』類問題,先用 workspaceSymbol(或 grep)定位符號宣告的確切位置,"
    "再對該位置用 findReferences 或 prepareCallHierarchy → incomingCalls;"
    "枚舉/計數題,用 LSP 與 grep 兩種方法互相覆核數字一致後才回答。")

HINTED_TEMPLATE = h.LSP_TEMPLATE.replace(
    "請優先用 LSP 工具回答,",
    "請優先用 LSP 工具回答。" + HINT)

OUT = os.path.expanduser("~/kernel-bench/v6-lsp/hint-probe")
TARGETS = ("WRQ-009", "WRQ-019", "WRQ-016")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    qs = {q["id"]: q for q in h.load_questions()}
    results = []
    for qid in TARGETS:
        q = qs[qid]
        h.prep_lsp_tree(q["repo"])
        for rep in (1, 2, 3):
            out_path = f"{OUT}/{qid}_lsphint_r{rep}.json"
            if os.path.exists(out_path):
                print(f"{qid} r{rep} done, skip", flush=True)
                continue
            prompt = HINTED_TEMPLATE.format(question=q["question"])
            print(f"=== {qid} lsphint r{rep} ===", flush=True)
            dt, rc = h.run_claude(prompt, h.lsp_workdir(q["repo"]),
                                  out_path, dict(os.environ))
            s = h.summarize(out_path)
            s.update({"id": qid, "rep": rep, "wall_s": round(dt, 1),
                      "rc": rc})
            results.append(s)
            print(f"    done {dt:.0f}s rc={rc} cost=${s.get('cost_usd')}",
                  flush=True)
    with open(f"{OUT}/probe-summary.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
