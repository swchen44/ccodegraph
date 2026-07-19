#!/bin/bash
# PostToolUse hook:對被編輯的 C 檔跑 clangd --check,錯誤注入 context
input=$(cat)
fp=$(echo "$input" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
case "$fp" in
  *.c|*.h)
    errs=$(cd "$(dirname "$fp")" && clangd --check="$fp" --log=error 2>&1 | grep -E "^E\[" | head -10)
    if [ -n "$errs" ]; then
      python3 -c "
import json, sys
errs = sys.stdin.read()
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',
  'additionalContext': '[diagnostics] clangd errors in the file you just edited:\n' + errs}}))
" <<< "$errs"
    fi
    ;;
esac
exit 0
