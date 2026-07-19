#!/bin/bash
# verify_ET-005.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"/wpa_supplicant
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
SIG=$(grep -c "} sig;" ../src/drivers/driver.h)
if [ "$SIG" -ge 1 ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="sig_struct=$SIG(站點由編譯器保證)"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
