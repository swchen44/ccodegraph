# ET-008(api-migration/hard,redis)

## 任務原文

repo 決定棄用 lookupKeyReadOrReply(c, key, reply)。請:①新增 robj *lookupKeyReadOrReplyEx(robj *key, client *c, robj *reply)(參數順序改為 key 在前,行為與舊函式完全相同);②把整個 repo 所有呼叫點遷移到新函式(注意參數對調);③刪除舊函式的宣告與定義。舊名在程式碼中不得殘留(註解不限)。完成後 `make` 全綠。

## GT 與驗收

站點(ET-008-sites.txt):37 呼叫點/10 檔 + 宣告/定義。驗收:build 綠 + 程式碼中 lookupKeyReadOrReply( 僅剩 Ex 版 + Ex 呼叫數 ≥37。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
