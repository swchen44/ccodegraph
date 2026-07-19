#!/usr/bin/env python3
"""tools/run_v8_slow.py — v8 慢 build 編輯對決 harness(v7 底)。

差異:①prep 後裝 slow-build wrapper(強制 clean rebuild + 校準延遲:
wpa ~110s/redis ~124s 每次 make,單目標與既存檔繞道均被攔截,
Makefile-remaking 與遞迴重入均已防護);②prompt 附慢 build 告知;
③timeout 3600;④verify 前拆殼(還原 Makefile.real)。原 v7 註解:

四臂(none/lsp-on/lsp-off/ccodegraph)x 8 題 x N=3;每 run 全新樹
(編輯任務污染樹)。裁判 = repo 內 verify_ET-00X.sh(編譯器機械判分),
run 完立即執行並記入 summary。條件:claude-sonnet-5、budget $4、
timeout 2400s、循序;resume key = (qid, arm, rep)。

臂差異(計畫 §1「路線對決」):
- none:無工具。
- lsp-on:clangd plugin(diagnostics on)+ PostToolUse hook(clangd
  --check 編輯檔 → additionalContext;Phase 0 驗證的可靠通道)+ bear
  真實 compile DB(v7 專用:compdb-{repo}-v7.json,路徑重寫)。
- lsp-off:clangd-lsp-nodiag plugin(diagnostics false)、無 hook,
  同一份 compile DB——隔離 diagnostics 淨貢獻。
- ccodegraph:合成模式(不給 compile DB;zero-build 定位主張)+ SKILL。

注入題(ET-003/004)prep 時以 sed 重放注入(與歸檔 patch 等價;
Phase 1 已逐一驗證 fire)。

用法:python3 tools/run_v7_edit.py <out_dir> [ET-00X ...] [arms=a,b] [reps=N]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

CCG_REPO = os.path.expanduser("~/git/ccodegraph")
CCG_PY = os.path.join(CCG_REPO, "ccodegraph.py")
CCG_SKILL = os.path.join(CCG_REPO, "skills/ccodegraph/SKILL.md")
V7DIR = os.path.join(CCG_REPO, "docs/research/hard-benchmark/v7")
QS_JSONL = os.path.join(V7DIR, "questions-v7.jsonl")
V7_WORK = os.path.expanduser("~/kernel-bench/v7")
HOOK_SRC = os.path.expanduser("~/kernel-bench/v7/gate-diag/diag-hook.sh")

REPOS = {
    "wpa": os.path.expanduser(
        "~/git/cbm-vs-codegraph-bench/repos/wpa_supplicant"),
    "redis": os.path.expanduser("~/git/cbm-vs-codegraph-bench/repos/redis"),
}
COMPDB = {k: os.path.join(V7_WORK, f"compdb-{k}-v7.json") for k in REPOS}
WPA_CONFIG = os.path.join(V7_WORK, "wpa-build.config")
GATE_TREE = {"wpa": os.path.join(V7_WORK, "gate-wpa"),
             "redis": os.path.join(V7_WORK, "gate-redis")}

MODEL = "claude-sonnet-5"
ARMS = ("none", "lsp-on", "lsp-off", "ccodegraph")
N_REPS = 3

BASE_TAIL = ("此專案 build 較慢:每次 make(任何目標)都會強制全量"
             "重建,約需 1 分鐘,請自行權衡驗證策略。\n"
             "任務:{task}\n完成修改後即可結束(不需要 git 操作、"
             "不需要總結報告,確保 build 通過即可)。")

TPL_NONE = ("你在一個 C 專案 repo 的可寫工作樹。用 shell 指令(grep/sed/"
            "find/make)與 Read/Edit 工具完成以下程式碼修改任務,"
            "可隨時自行跑 make 驗證。" + BASE_TAIL)

TPL_LSP = ("你在一個 C 專案 repo 的可寫工作樹。此環境已啟用 clangd LSP"
           "(專案根有真實 compile_commands.json)。有一個 `LSP` 工具"
           "(若不在目前工具清單,先用 ToolSearch query=\"select:LSP\" "
           "載入),操作:goToDefinition / findReferences / hover / "
           "documentSymbol / workspaceSymbol / prepareCallHierarchy / "
           "incomingCalls / outgoingCalls;參數 filePath + line + "
           "character(1-based)。也可用 shell 與 Read/Edit,"
           "可隨時自行跑 make 驗證。" + BASE_TAIL)

TPL_CCG = ("你在一個 C 專案 repo 的可寫工作樹。這裡有 ./ccodegraph.py "
           "程式碼知識圖工具,圖已建好在 .ccodegraph/(zero-build 模式,"
           "不需要 compile DB)。可用它定位符號的所有使用點(explore/"
           "callers/callees/sql),搭配 shell 與 Read/Edit 完成修改,"
           "可隨時自行跑 make 驗證。" + BASE_TAIL)

# 注入重放(Phase 1 驗證過的 sed;與 v7/patches/ 歸檔等價)
INJECT = {
    "ET-003": [
        ("src/t_string.c", "604s/checkStringLength/checkStrLength/"),
        ("src/latency.c",
         "89s/samples\\[ts->idx\\].latency = latency;"
         "/samples[ts->idx].latency_ms = latency;/"),
    ],
    "ET-004": [
        ("wpa_supplicant/config_file.c", "29s/os_strlen(buf)/os_strlength(buf)/"),
        ("wpa_supplicant/scan.c",
         "1137s/eloop_register_timeout(sec, usec, wpa_supplicant_scan, "
         "wpa_s, NULL);/eloop_register_timeout(sec, usec, "
         "wpa_supplicant_scan, wpa_s);/"),
        ("wpa_supplicant/events.c", "132s/wpa_s->current_ssid/wpa_s->cur_ssid/"),
        ("src/utils/eloop.c", "615s/timeout->time.sec/timeout->time.seconds/"),
        ("src/rsn_supp/wpa.c", "103s/sm->pairwise_cipher/sm->pairwise_ciph/"),
    ],
}


def load_questions() -> list[dict[str, Any]]:
    with open(QS_JSONL) as f:
        return [json.loads(line) for line in f if line.strip()]


def clean_tree(repo: str, dst: str) -> None:
    r = subprocess.run(f"git archive HEAD | tar -x -C {dst!r}",
                       shell=True, cwd=REPOS[repo],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"git archive failed: {r.stderr}")
    if repo == "wpa":
        shutil.copy(WPA_CONFIG, os.path.join(dst, "wpa_supplicant/.config"))


def rewrite_compdb(repo: str, tree: str) -> None:
    with open(COMPDB[repo]) as f:
        db = json.load(f)
    old_root = GATE_TREE[repo]
    def rw(s: str) -> str:
        return s.replace(old_root, tree)
    for e in db:
        for k in ("directory", "file", "output", "command"):
            if k in e:
                e[k] = rw(e[k])
        if "arguments" in e:
            e["arguments"] = [rw(a) for a in e["arguments"]]
    with open(os.path.join(tree, "compile_commands.json"), "w") as f:
        json.dump(db, f, indent=1)


def apply_injection(qid: str, tree: str) -> None:
    for relpath, sedexpr in INJECT.get(qid, []):
        p = os.path.join(tree, relpath)
        r = subprocess.run(["sed", "-i", "", sedexpr, p],
                           capture_output=True, text=True)
        assert r.returncode == 0, (relpath, r.stderr)


def prep(q: dict[str, Any], arm: str) -> tuple[str, str]:
    tree = tempfile.mkdtemp(prefix=f"v7-{q['id']}-{arm}-")
    clean_tree(q["repo"], tree)
    apply_injection(q["id"], tree)
    if arm in ("lsp-on", "lsp-off"):
        rewrite_compdb(q["repo"], tree)
        plugin = ("clangd-lsp@local-bench" if arm == "lsp-on"
                  else "clangd-lsp-nodiag@local-bench")
        settings: dict[str, Any] = {"enabledPlugins": {plugin: True}}
        if arm == "lsp-on":
            shutil.copy(HOOK_SRC, os.path.join(tree, "diag-hook.sh"))
            os.chmod(os.path.join(tree, "diag-hook.sh"), 0o755)
            settings["hooks"] = {"PostToolUse": [{
                "matcher": "Edit|Write",
                "hooks": [{"type": "command",
                           "command": "$CLAUDE_PROJECT_DIR/diag-hook.sh"}]}]}
        os.makedirs(os.path.join(tree, ".claude"), exist_ok=True)
        with open(os.path.join(tree, ".claude", "settings.json"), "w") as f:
            json.dump(settings, f, indent=2)
        tpl = TPL_LSP
    elif arm == "ccodegraph":
        shutil.copy(CCG_PY, tree)
        os.makedirs(os.path.join(tree, ".claude", "skills", "ccodegraph"),
                    exist_ok=True)
        shutil.copy(CCG_SKILL, os.path.join(
            tree, ".claude", "skills", "ccodegraph", "SKILL.md"))
        subprocess.run(["python3", "ccodegraph.py", "build", "-p", ".",
                        "-j", "8"], cwd=tree, check=True,
                       capture_output=True)
        tpl = TPL_CCG
    else:
        tpl = TPL_NONE
    install_slow_wrapper(q["repo"], tree)
    return tpl.format(task=q["task"]), tree


WRAPPER_TMPL = os.path.expanduser("~/kernel-bench/v8/make-wrapper.tmpl")
# 校準至每次 make ≈ 60s(使用者定案 2026-07-20;實測:wpa 總時 =
# delay+~10s、redis = delay+~34s)
WRAP_SPEC = {"redis": ("src/Makefile", "25"),
             "wpa": ("wpa_supplicant/Makefile", "50")}


def install_slow_wrapper(repo: str, tree: str) -> None:
    rel, delay = WRAP_SPEC[repo]
    mk = os.path.join(tree, rel)
    os.rename(mk, mk + ".real")
    with open(WRAPPER_TMPL) as f:
        body = f.read().replace("__DELAY__", delay)
    with open(mk, "w") as f:
        f.write(body)


def remove_slow_wrapper(repo: str, tree: str) -> None:
    rel, _ = WRAP_SPEC[repo]
    mk = os.path.join(tree, rel)
    if os.path.exists(mk + ".real"):
        os.replace(mk + ".real", mk)


def run_claude(prompt: str, cwd: str, out_path: str) -> tuple[float, int]:
    cmd = ["claude", "-p", prompt, "--setting-sources", "project",
           "--output-format", "json", "--permission-mode",
           "bypassPermissions", "--model", MODEL, "--max-budget-usd", "4"]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       timeout=3600)
    dt = time.time() - t0
    with open(out_path, "w") as f:
        f.write(r.stdout)
    if r.returncode != 0:
        with open(out_path + ".stderr", "w") as f:
            f.write(r.stderr)
    return dt, r.returncode


def run_verify(qid: str, tree: str, repo: str = "") -> str:
    if repo:
        remove_slow_wrapper(repo, tree)
    vs = os.path.join(V7DIR, "verify", f"verify_{qid}.sh")
    r = subprocess.run(["bash", vs, tree], capture_output=True, text=True,
                       timeout=1200)
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("RESULT:"):
            return line
    return f"RESULT: FAIL reason=no-result rc={r.returncode}"


def summarize(out_path: str) -> dict[str, Any]:
    try:
        with open(out_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}
    u = data.get("usage", {})
    return {"cost_usd": data.get("total_cost_usd"),
            "num_turns": data.get("num_turns"),
            "output_tokens": u.get("output_tokens"),
            "duration_ms": data.get("duration_ms"),
            "is_error": data.get("is_error"),
            "session_id": data.get("session_id")}


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v7-runs"
    arm_filter: tuple[str, ...] = ARMS
    n_reps = N_REPS
    rest = []
    for a in sys.argv[2:]:
        if a.startswith("arms="):
            arm_filter = tuple(a.split("=", 1)[1].split(","))
            assert all(x in ARMS for x in arm_filter), arm_filter
        elif a.startswith("reps="):
            n_reps = int(a.split("=", 1)[1])
        else:
            rest.append(a)
    only = set(rest) or None
    os.makedirs(out_dir, exist_ok=True)
    spath = os.path.join(out_dir, "summary.json")
    summary: list[dict[str, Any]] = []
    if os.path.exists(spath):
        with open(spath) as f:
            summary = json.load(f)
    done = {(s["id"], s["arm"], s.get("rep", 1))
            for s in summary if s.get("rc") == 0}

    for q in load_questions():
        if only and q["id"] not in only:
            continue
        for rep in range(1, n_reps + 1):
            for arm in arm_filter:
                key = (q["id"], arm, rep)
                if key in done:
                    print(f"=== {q['id']} {arm} r{rep} done, skip ===",
                          flush=True)
                    continue
                print(f"=== {q['id']} {arm} r{rep} ({q['repo']}) ===",
                      flush=True)
                tree = None
                try:
                    prompt, tree = prep(q, arm)
                    out_path = os.path.join(
                        out_dir, f"{q['id']}_{arm}_r{rep}.json")
                    dt, rc = run_claude(prompt, tree, out_path)
                    verdict = run_verify(q["id"], tree, q["repo"])
                    s = summarize(out_path)
                    s.update({"id": q["id"], "arm": arm, "rep": rep,
                              "wall_s": round(dt, 1), "rc": rc,
                              "verdict": verdict})
                    summary = [x for x in summary
                               if not (x["id"] == q["id"]
                                       and x["arm"] == arm
                                       and x.get("rep", 1) == rep)]
                    summary.append(s)
                    with open(spath, "w") as f:
                        json.dump(summary, f, indent=2)
                    print(f"    {dt:.0f}s rc={rc} "
                          f"cost=${s.get('cost_usd')} {verdict}",
                          flush=True)
                except (subprocess.CalledProcessError,
                        subprocess.TimeoutExpired) as e:
                    print(f"    FAILED: {e}", flush=True)
                    summary.append({"id": q["id"], "arm": arm, "rep": rep,
                                    "rc": -1, "error": str(e)[:300]})
                    with open(spath, "w") as f:
                        json.dump(summary, f, indent=2)
                finally:
                    if tree:
                        shutil.rmtree(tree, ignore_errors=True)
    print("=== done ===")


if __name__ == "__main__":
    main()
