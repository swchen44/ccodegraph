# ET-003(injected-bugs/easy,redis)

## 任務原文

這棵樹目前 `make` 失敗(兩個編譯錯誤)。請找出並修復,恢復原本的正確行為(修根因,不是註解掉或繞過)。完成後 build 全綠。

## GT 與驗收

注入(patches/ET-003a+b.patch):t_string.c:604 checkStringLength 被 typo 成 checkStrLength;latency.c:89 欄位 .latency 被改 .latency_ms。驗收:build 綠 + 兩處恢復原樣(無 checkStrLength/latency_ms 殘留;checkStringLength 呼叫數恢復 4)。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
