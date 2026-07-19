# ET-005(struct-extraction/easy,wpa)

## 任務原文

把 struct wpa_scan_res(src/drivers/driver.h)的 qual 與 noise 兩個欄位移入新的內嵌結構欄位 sig:`struct { int qual; int noise; } sig;`(取代原兩欄位位置),並更新整個 repo 所有使用點(r->qual → r->sig.qual 等)。完成後 wpa_supplicant/ 下 build 全綠。

## GT 與驗收

編譯器點名 12 站點/3 檔:bss.c:280,281;events.c:1435,1436;scan.c:1701,1712,1784,1785,1792,1793,1872,1878。驗收:build 綠 + driver.h 含 sig 子結構。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
