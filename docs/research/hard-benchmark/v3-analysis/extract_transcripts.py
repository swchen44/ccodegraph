#!/usr/bin/env python3
"""Extract per-run tool-call / token-hotspot data from the 88 v3 session transcripts.

For each (question, tool) run: locate the session transcript by session_id,
walk every tool_use -> tool_result pair, and record:
  - tool name (Bash/Read/...)
  - a normalized "command signature" (first token(s) of a Bash command, or
    "Read" for file reads)
  - the byte length of the tool_result content (this is what actually gets
    fed back into context and burns tokens)

Writes a single consolidated JSON to analysis_raw.json for downstream
aggregation (by tool arm, by command signature, by question).
"""
import glob
import json
import os

SUMMARY = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/hard-ab-v3/summary.json"
PROJECTS_GLOB = os.path.expanduser("~/.claude/projects/*/{}.jsonl")
OUT = "/Users/swchen.tw/.claude/jobs/5e00d3b7/tmp/analysis/analysis_raw.json"


def result_text_len(content):
    """tool_result content can be a string or a list of content blocks."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    total += len(block["text"])
                elif "content" in block:
                    total += result_text_len(block["content"])
            elif isinstance(block, str):
                total += len(block)
        return total
    return len(json.dumps(content))


def normalize_command(cmd):
    """Reduce a bash command to a short signature for grouping."""
    cmd = cmd.strip()
    first_line = cmd.split("\n")[0].strip()
    tokens = first_line.split()
    if not tokens:
        return "(empty)"
    t0 = os.path.basename(tokens[0])
    if t0 in ("grep", "rg"):
        return "grep"
    if t0 == "awk":
        return "awk"
    if t0 == "sed":
        return "sed"
    if t0 == "cat":
        return "cat"
    if t0 == "find":
        return "find"
    if t0 == "ls":
        return "ls"
    if t0 == "python3" and "ccodegraph.py" in cmd:
        # e.g. python3 ccodegraph.py explore/sql/callers/...
        parts = cmd.split("ccodegraph.py", 1)[1].split()
        verb = parts[0] if parts else "?"
        return f"ccodegraph:{verb}"
    if "ccodegraph.py" in tokens[0] or t0 == "ccodegraph.py":
        parts = cmd.split("ccodegraph.py", 1)[1].split()
        verb = parts[0] if parts else "?"
        return f"ccodegraph:{verb}"
    if "codegraph" in t0 and "cbm" not in cmd:
        verb = tokens[1] if len(tokens) > 1 else "?"
        return f"codegraph:{verb}"
    if "codebase-memory-mcp" in cmd or "cbm" in t0:
        # e.g. CBM_CACHE_DIR=... /path/codebase-memory-mcp cli query_graph ...
        if "query_graph" in cmd:
            return "cbm:query_graph"
        if "trace_path" in cmd:
            return "cbm:trace_path"
        if "index_repository" in cmd:
            return "cbm:index_repository"
        return "cbm:other"
    if t0 == "sqlite3":
        return "sqlite3"
    return f"other:{t0}"


def main():
    with open(SUMMARY) as f:
        summary = json.load(f)

    results = []
    missing = []
    for entry in summary:
        sid = entry.get("session_id")
        if not sid:
            missing.append((entry["id"], entry["tool"], "no session_id"))
            continue
        matches = glob.glob(PROJECTS_GLOB.format(sid))
        if not matches:
            missing.append((entry["id"], entry["tool"], "no transcript file"))
            continue
        path = matches[0]
        calls = []
        with open(path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                content = obj.get("message", {}).get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        name = c.get("name")
                        inp = c.get("input", {})
                        if name == "Bash":
                            sig = normalize_command(inp.get("command", ""))
                        elif name == "Read":
                            sig = "Read"
                        else:
                            sig = f"other-tool:{name}"
                        calls.append({"tool_use_id": c.get("id"), "name": name,
                                     "sig": sig})
                    elif isinstance(c, dict) and c.get("type") == "tool_result":
                        # attach byte length to the most recent matching call
                        tuid = c.get("tool_use_id")
                        blen = result_text_len(c.get("content"))
                        for call in reversed(calls):
                            if call["tool_use_id"] == tuid and "result_bytes" not in call:
                                call["result_bytes"] = blen
                                break
        for call in calls:
            call.setdefault("result_bytes", 0)
        results.append({
            "id": entry["id"], "tool": entry["tool"],
            "cost_usd": entry.get("cost_usd"),
            "input_tokens": entry.get("input_tokens"),
            "output_tokens": entry.get("output_tokens"),
            "cache_read": entry.get("cache_read"),
            "cache_creation": entry.get("cache_creation"),
            "num_turns": entry.get("num_turns"),
            "duration_ms": entry.get("duration_ms"),
            "calls": calls,
        })

    with open(OUT, "w") as f:
        json.dump({"results": results, "missing": missing}, f)
    print(f"processed {len(results)} runs, missing {len(missing)}")
    if missing:
        for m in missing[:10]:
            print("  MISSING:", m)


if __name__ == "__main__":
    main()
