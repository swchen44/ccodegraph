# ET-007(api-migration/easy,wpa)

## 任務原文

把 wpa_supplicant/config_file.c 的 static 函式 wpa_config_get_line 改名為 wpa_config_read_line,並把 stream 參數移到第一位(新簽名:static char * wpa_config_read_line(FILE *stream, char *s, int size, int *line, char **_pos)),更新檔案內所有呼叫點的名稱與參數順序。舊名不得殘留。完成後 wpa_supplicant/ 下 build 全綠。

## GT 與驗收

站點(ET-007-sites.txt):定義:64 + 呼叫 178, 236, 292, 400。驗收:build 綠 + wpa_config_get_line 零殘留 + wpa_config_read_line 出現 ≥5 次。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
