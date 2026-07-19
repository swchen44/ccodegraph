#!/bin/bash
# verify_ET-006.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
CS=$(grep -c "} core_stats;" src/server.h)
OLD=$(grep -rcw "stat_numcommands\|stat_numconnections\|stat_expiredkeys" src --include="*.c" --include="*.h" | awk -F: "{s+=\$2} END{print s}")
if [ "$CS" -ge 1 ] && [ "$OLD" = "0" ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="core_stats=$CS old_names=$OLD"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
