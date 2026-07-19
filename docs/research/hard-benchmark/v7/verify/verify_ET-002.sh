#!/bin/bash
# verify_ET-002.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"/wpa_supplicant
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
DEF=$(grep -c "os_get_time(struct os_time \*t, int clock_source)" ../src/utils/os.h)
if [ "$DEF" -ge 1 ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="decl=$DEF(站點覆蓋由編譯器保證)"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
