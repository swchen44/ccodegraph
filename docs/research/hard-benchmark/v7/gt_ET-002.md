# ET-002(type-propagation/hard,wpa)

## 任務原文

為 os_get_time(宣告 src/utils/os.h、定義 src/utils/os_unix.c)增加第二個參數 int clock_source:clock_source==0 時行為與現在完全相同(其他值目前保留,一律視同 0 處理)。更新整個 repo 所有呼叫點傳入 0。完成後 wpa_supplicant/ 下 `make` 必須全綠。

## GT 與驗收

編譯器點名 10 站點/9 檔:ieee802_11_shared.c:440, ieee802_11.c:216, random.c:142, eapol_auth_sm.c:1306, tlsv1_client_write.c:54, x509v3.c:1852, common.c:240, wpa_debug.c:73, notify.c:512, notify.c:528(+宣告/定義)。驗收:build 綠 + 新參數存在。注意:不在本 build config 的檔案(如部分 driver)之呼叫點不在 GT 內,但若 agent 全改亦不扣分。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
