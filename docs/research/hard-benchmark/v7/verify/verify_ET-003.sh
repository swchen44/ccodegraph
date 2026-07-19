#!/bin/bash
# verify_ET-003.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
BAD=$(grep -rc "checkStrLength\|latency_ms" src/t_string.c src/latency.c | awk -F: "{s+=\$2} END{print s}")
CALLS=$(grep -c "checkStringLength(" src/t_string.c)
if [ "$BAD" = "0" ] && [ "$CALLS" -ge 4 ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="bad_tokens=$BAD calls=$CALLS/4"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
