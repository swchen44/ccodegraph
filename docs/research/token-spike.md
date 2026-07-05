# R4a:token A/B spike — grep/Read 路徑 vs 圖查詢路徑(2026-07-05)

> 目的:提早驗證 W1(token 經濟是第一因)。**代理量測**,不是真 LLM 執行:
> 成本 = agent 為答對所需攝取的資訊量(bytes,token ≈ B/4)。
> grep 路徑用對 agent **有利**的機械模型:grep 輸出 + 每命中僅讀 ±20 行做歸戶、
> 查詢一次到位、零重試。真 LLM A/B(ccq token-cost 方法,N=3)是後續項。

## 結果(wpa_supplicant,620 檔,L0+L1+L3 圖)

| 任務 | grep 路徑 | 圖路徑 | 節省 |
|---|---|---|---|
| T1 callers(eloop_remove_timeout) | 24,642 B | 842 B | **29×** |
| T2 fnptr handler 反查(driver_nl80211_scan2) | 17,286 B(3 跳) | 230 B | **75×** |
| T3 writers(wpa_debug_level) | 101,153 B | 1,139 B | **89×** |
| T4 impact -d2(eloop_register_timeout,雙定義) | 693,562 B | 56,448 B(含提示往返) | **12×** |
| T5 who-includes(eloop.h) | 2,950 B | 2,994 B | 1.0× |
| T6 callees(eloop_run) | 7,800 B | 3,513 B | 2.2× |
| T7 callback 反查(freq_cmp) | 4,936 B | 62 B | **80×** |
| T8 定義定位(hostapd_setup_bss) | 3,380 B | 57 B | **59×** |
| **合計** | **855,709 B(~214k tok)** | **65,285 B(~16k tok)** | **13×** |

## 判讀

- **W1 在代理層成立**:整體 13×,中位數 ~44×。省最多的是**歸戶重的問題**
  (T3 誰寫全域 89×——grep 的 `=` 噪音要人肉排)與**多跳問題**(T2 fnptr 75×)。
- **誠實揭露弱項**:T5(includes)grep 平手——`#include "x.h"` 本來就是精確
  文字模式,圖在這題只贏在函式級聚合,不贏 token。T6 僅 2.2×(讀函式體
  本來就不貴)。
- **T4 的插曲是真發現**:雙定義符號的 impact 因 D4 預設回空,原本無提示
  (1 byte,agent 會誤判「無影響」)。已修:空結果 + 存在 ambiguous 邊時印
  「N ambiguous edges exist — rerun with --ambiguous」(P7)。修後 agent
  流程兩次往返仍 12×。
- **限制**:byte 代理 ≠ 真 token;grep 模型假設 agent 查詢一次到位(現實會
  重試,grep 路徑實際更貴);未計 LLM 推理 token。結論方向可信、倍數保守。

## 後續

真 LLM A/B(同 model 同 prompt,PATH 有無 ccodegraph 各跑一次,讀實際計費
token)排在 R4 查詢層設計時一併——屆時的動詞是為 LLM 設計的最終形狀,
量出來的才是產品數字。
