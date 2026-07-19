# ET-004(injected-bugs/hard,wpa)

## 任務原文

這棵樹目前 `make` 失敗(五個編譯錯誤,分佈多個檔案)。請全部找出並修復,恢復原本的正確行為(修根因,不是繞過)。完成後 wpa_supplicant/ 下 build 全綠。

## GT 與驗收

注入(patches/ET-004.patch):config_file.c:29 os_strlen→os_strlength(typo);scan.c:1137 eloop_register_timeout 少最後一個 NULL 參數;events.c:132 current_ssid→cur_ssid;eloop.c:615 time.sec→time.seconds;wpa.c:103 pairwise_cipher→pairwise_ciph。驗收:build 綠 + 五處原語意恢復、六個錯誤 token 零殘留。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
