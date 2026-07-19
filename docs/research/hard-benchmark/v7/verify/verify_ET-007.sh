#!/bin/bash
# verify_ET-007.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"/wpa_supplicant
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
OLD=$(grep -c "wpa_config_get_line" config_file.c)
NEW=$(grep -c "wpa_config_read_line" config_file.c)
if [ "$OLD" = "0" ] && [ "$NEW" -ge 5 ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="old=$OLD new=$NEW/5"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
