#!/bin/bash
# verify_ET-008.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
OLDONLY=$(grep -rn "lookupKeyReadOrReply(" src --include="*.c" --include="*.h" | grep -vc "lookupKeyReadOrReplyEx(")
NEW=$(grep -rc "lookupKeyReadOrReplyEx(" src --include="*.c" --include="*.h" | awk -F: "{s+=\$2} END{print s}")
if [ "$OLDONLY" = "0" ] && [ "$NEW" -ge 38 ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="old_calls=$OLDONLY new=$NEW/38"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
