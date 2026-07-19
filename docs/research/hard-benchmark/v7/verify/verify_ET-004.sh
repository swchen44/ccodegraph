#!/bin/bash
# verify_ET-004.sh <tree-root> — v7 機械驗收;最後一行 RESULT: PASS|FAIL ...
T="$1"; [ -d "$T" ] || { echo "RESULT: FAIL reason=no-tree"; exit 1; }
cd "$T"/wpa_supplicant
make -k -j8 > /tmp/v7v.log 2>&1
ERRS=$(grep -cE ": error:" /tmp/v7v.log)
BUILD=$([ "$ERRS" = "0" ] && echo 1 || echo 0)
cd ..
BAD=$(grep -rcw "os_strlength\|cur_ssid\|time\.seconds\|pairwise_ciph" wpa_supplicant/config_file.c wpa_supplicant/events.c src/utils/eloop.c src/rsn_supp/wpa.c | awk -F: "{s+=\$2} END{print s}")
NARG=$(sed -n "1137p" wpa_supplicant/scan.c | grep -c "wpa_s, NULL")
if [ "$BAD" = "0" ]; then SITES_OK=1; else SITES_OK=0; fi
DETAIL="bad_tokens=$BAD scan1137_null=$NARG"
if [ "$BUILD" = "1" ] && [ "$SITES_OK" = "1" ]; then R=PASS; else R=FAIL; fi
echo "RESULT: $R build=$BUILD errors=$ERRS $DETAIL"
