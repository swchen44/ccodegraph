# R4 驗收:真 LLM A/B(codex/gpt-5.5,實際計費 token,2026-07-05)

> 方法:同模型、同任務,A 臂 = 給 ccodegraph + SKILL.md、禁 grep;B 臂 = 只准
> shell(grep/awk/sed/find)。arena = wpa_supplicant(620 檔)。token 取 codex
> 每場自行回報的 tokens used(含全部往返)。**N=1 先導**,變異數未量。

## 結果

| 任務 | A tokens | B tokens | A 正確性 | B 正確性 |
|---|---|---|---|---|
| T1 callers(eloop_remove_timeout) | 14,613 | 25,024 | ✓ 4/4 | ✓ 4/4 |
| T2 fnptr `.scan2` 5 handlers | 28,213 | 14,114 | ✓ 5/5 | ✓ 5/5 |
| T3 誰**寫** wpa_debug_level | 40,301 | 50,951 | **✓ 13/13** | **✗ 9/13**(漏 WinMain、main.c/main_none/main_winsvc 的寫入者) |
| T4 callback(freq_cmp) | 17,058 | 18,465 | ✓(且主動 SQL 驗證邊、標注 heur) | ✓ |
| T5 誰 include eloop.h(數量) | 33,353 | 6,508 | **✓ 117** | **✗ 59**(只 grep 到 `"eloop.h"` 寫法,漏 `"utils/eloop.h"` 58 檔——**靜默錯 2 倍**) |
| **合計** | **133,538** | **115,062** | **5/5 全對** | **3/5** |

## 判讀(誠實版)

1. **token 大致打平**(A 貴 16%)——不是先前 byte 代理量測暗示的一面倒。
   原因:A 臂有讀 SKILL 的固定開銷 + agent 多輪往返時 codex 逐輪重送 context;
   B 臂在「一發 grep 就中」的題(T2/T5)極便宜。byte 代理量的是資訊量,
   真 agent 的成本大宗是輪數與 context 重送——兩個量測都對,量的東西不同。
2. **正確性 5/5 vs 3/5 才是本體**:B 臂兩題**靜默答錯**——T5 差 2 倍
  (include 寫法變體)、T3 漏 31% 寫入者。W1 的原始主張成立:grep 的問題
   不是貴,是「便宜地答錯而且不自知」。兩題都是使用者會據以做決策的類型
  (改 header 的影響面、改全域的爆炸面)。
3. **SKILL 的風險章有效**:A 臂在 T4 主動用 SQL 覆核 callback 邊並在答案標注
   「heuristic 來源」——正是風險章教的行為。
4. 改善項:T5 A 臂多花 33k 在「不信任 who-includes 又用 SQL 重數」;SKILL
   已補一句「who-includes 輸出已去重,可直接數行」。

## 限制與後續

- N=1 先導;正式版 N=3 + 更多任務(含需要 `--ambiguous` 判讀的題)。
- codex 的 token 計法(逐輪重送)對多輪 agent 偏不利;換用有 cache 的執行面
  (Claude Code)數字會偏向 A 臂。
- 兩臂皆未限制輪數;B 臂答錯時並無「不確定」表述——silent。

## 行為分析(#9:兩臂各自「怎麼完成事情」;從 exec 序列重建)

**A 臂的固定模式(SKILL 紀律被遵守)**:每場都是 `--help` → `skill`(讀說明)→
`schema`(Step 0)→ 動詞。T1 只用 **3 個 exec** 就答對;T4 用 8 個(其中兩個是
主動 SQL 覆核 callback 邊——風險章教的行為)。失手處:T2 花了 20 個 exec
(對 fnptr 題過度探索,反覆下 SQL 而不是直接信 `callers` 的 [fnptr] 邊);
T5 甚至去讀了 ccodegraph.py 原始碼確認語意(11 exec)——**對工具輸出的不信任
是 A 臂 token 偏高的主因**,SKILL 已補「who-includes 已去重,直接數」對症。

**B 臂的模式:少數幾發 grep + 大量 sed 讀窗**:T4 靠 4 個 exec 運氣好一發中;
T1 用 13 個(grep 全庫 + 5 個 sed 讀窗做人肉歸戶);T3 用 19 個 exec 讀了 11
個視窗**仍漏掉 4 個寫入者**(WinMain、三個平台 main——散在它沒打開的檔裡)。
**T5 是教科書級案例:整場只有 1 個 exec**——一條精心構造的 find|grep 管線,
輸出 59,自信作答,**錯 2 倍**(`#include "utils/eloop.h"` 寫法的 58 檔全漏)。
便宜、優雅、錯誤、且毫無不確定性表述。

**總結**:A 臂的成本花在「讀說明 + 驗證自己」——可攤提、可優化(SKILL 措辭
每改一句,所有未來查詢受益);B 臂的成本花在「人肉歸戶讀窗」——不可攤提,
且召回缺口(路徑變體、跨檔散佈)結構性存在,exec 越少錯得越自信。
(兩臂各有 2-3 個 exec 浪費在 codex 環境的 plugin 檔案上,對稱、不影響對比。)
