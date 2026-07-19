# ET-001(type-propagation/easy,redis)

## 任務原文

為 src/t_string.c 的 static 函式 checkStringLength 增加第四個參數 int quiet:quiet 非 0 時,超限情況下不呼叫任何 addReply* 回覆(靜默回傳 C_ERR),其餘行為不變。更新檔案內所有呼叫點傳入 0。完成後 `make` 必須全綠(零 error)。不要改動其他行為。

## GT 與驗收

編譯器點名站點:t_string.c 定義:26 + 呼叫 604, 623, 1391(參考編輯實測)。驗收:build 綠(站點覆蓋由編譯器保證)+ 定義帶 int quiet + quiet 分支存在。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
