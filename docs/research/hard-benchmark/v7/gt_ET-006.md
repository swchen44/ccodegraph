# ET-006(struct-extraction/hard,redis)

## 任務原文

把 struct redisServer(src/server.h)的三個欄位 stat_numcommands、stat_numconnections、stat_expiredkeys 移入新的子結構欄位 core_stats,成員名去掉 stat_ 前綴:`struct { long long numcommands; long long numconnections; long long expiredkeys; } core_stats;`。更新整個 repo 所有使用點(server.stat_numcommands → server.core_stats.numcommands 等)。完成後 `make` 全綠。

## GT 與驗收

編譯器點名 17 站點/7 檔:blocked.c:100;cluster.c:288;db.c:2817;networking.c:1633;server.c:1596,2122,2123,2168,2885,2886,2887,4187,6699,6700,6716;t_string.c:170,1311。驗收:build 綠 + server.h 含 core_stats + 三個舊欄位名零殘留。

(GT 建構法:型別傳播/抽結構=參考編輯後 `make -k` 編譯器點名;注入=patch 檔固定;API 遷移=grep 站點清單。詳 llm-ab-v7-plan.md §2。)
