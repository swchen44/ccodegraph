# GT case 2: SET command dispatch chain (redis)

Method: 手動追蹤 src/server.c 的 lookupCommand/processCommand 分派點,再逐層讀
src/t_string.c 與 src/db.c 的實作(非 grep 猜測,逐函式讀過)。

## 完整呼叫鏈(依序,含檔案:行)

1. `processCommand`(src/server.c)— 每個指令的總入口
2. `lookupCommand`(src/server.c:3611)/`lookupCommandLogic`(src/server.c:3595)— 依 argv[0] 查表
3. `cmd->proc` 分派 → `setCommand`(src/t_string.c:435)
4. `setCommand` 解析參數後呼叫 `setGenericCommand`(src/t_string.c,同檔)
5. `setGenericCommand` 內部:
   - `lookupKeyWriteWithLink(c->db,key,&link)` — 檢查 key 是否已存在
   - `setKeyByLink(c, c->db, key, valref, setkey_flags, &link)`(呼叫點 t_string.c:95,
     定義在 src/db.c:754)
6. `setKeyByLink`(src/db.c:754)分兩支:
   - **已存在**:`dbSetValue(db, key, valref, *link, 1, 1, ...)` + `notifyKeyspaceEvent(NOTIFY_OVERWRITTEN, "overwritten", ...)`(+ type 變更時多發一個 `type_changed` 事件)
   - **不存在**:`dbAddByLink(db, key, valref, link)`(src/db.c:460)→ 內部呼叫
     `dbAddInternal(db, key, valref, link, &keyMetaEmpty)`
   - 兩支之後都呼叫 `keyModified(c,db,key,*valref,...)` 做訊號通知
7. 回到 `setGenericCommand`:若有 expire 參數,呼叫 `setExpireByLink(...)`;
   最後 `notifyKeyspaceEvent(NOTIFY_STRING,"set",key,c->db->id)`

## 評分關鍵

- **score 3** 需要點名 `setKeyByLink` 這個中間層,且說出「已存在 vs 不存在」兩條分支各自
  呼叫什麼(`dbSetValue` vs `dbAddByLink`)。
- **score 2** 只到 `setGenericCommand` 就停,沒有繼續往下追 `setKeyByLink`/`dbAddByLink`/
  `dbSetValue`(這是最常見的「淺層追蹤」失敗模式——多跳鏈追到中途就當作終點)。
- **score 1** 只到 `setCommand`,或錯把 `lookupCommand` 當成寫入點。
