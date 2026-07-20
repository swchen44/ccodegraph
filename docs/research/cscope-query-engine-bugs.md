# cscope `-L` 查詢引擎的三類幻影 bug(2026-07-11,D17 副產品)

> TL;DR:cscope 15.9 的 crossref **建置端**是可靠的;但它自己的 `-L`
> **查詢端**在大檔/多行定義上會回錯行號、雙報 caller、丟整行結果——
> 三類 bug 都以「crossref 原始 bytes + 原始碼」雙重對質實證。任何以
> `cscope -L` 輸出為 ground truth 的工具(包括 D17 之前的 ccodegraph
> v1-v5 全部圖)都帶著這些幻影。D17 改為直接解析 crossref 後三類全消。
> 發現方法本身(差分測試 + 幻影自動判定)可複用。

## 背景與方法

D17 spike(`design.md` §8.5.6)把 L1 從「每符號 spawn 一個 `cscope -dL<q>`」
改為單遍解析 `-c`(未壓縮)crossref。為驗證解析器語意,我們寫了差分測試器:
對同一個 crossref,解析器輸出 vs 真 cscope `-L` 輸出逐符號對拍(wpa_supplicant
全量抽樣 ~3,400 查詢)。**預期解析器有 bug,結果多數殘餘差異反向指認了
oracle 的 bug**——每個案例都回到 crossref bytes 與原始碼仲裁,以下三類全部
可用 cscope 15.9(macOS/Homebrew)重現。

## Bug 1:行號漂移(幻影站點)

`cscope -d -f <db> -L3 os_free` 對 wpa 回報
`crypto_internal.c crypto_hash_finish 223 …os_free(ctx);`——但:

- crossref 對該檔的記錄從 222 直接跳 224,**根本沒有 223 行的記錄**;
- 原始碼 223 行是空白行,真正的 `os_free(ctx);` 在 **217** 行(有記錄)。

極端案例連**檔案**都漂移:`-L3 fst_group_get_id` 回報
`fst_internal.h ... 1255 ...`——`fst_internal.h` 只有 **49 行**;
該站點實際在 `fst_session.c:1255`。

規模:wpa/redis 邊集 diff 中所有「舊圖有、新圖無」且站點完全消失的邊
(wpa 56 + redis 36 站點),經自動幻影判定(dst 符號名是否出現在該行
原始碼)+ 人工抽樣,**100% 屬此類或 Bug 2**。行號超出檔尾的變體 13 例。
另有誤判讀寫的變體:`wpa_cli.c:390` 是 `if (ctrl_conn == NULL)`(讀),
`-L9`(assignments)卻回報了它——真正的賦值在下方數行。

## Bug 2:多行定義雙報 caller

```c
static RadiusRxResult
radius_das_disconnect(struct radius_das_data *das, ...)
```

`-L3 radius_msg_get_attr_ptr` 對此函式內的呼叫站點**同站點回兩列**:
caller=`RadiusRxResult`(回傳型別!)與 caller=`radius_das_disconnect`
各一列。crossref 中只有一個乾淨的 `$radius_das_disconnect` 定義標記
(32 行)——雙報是查詢端自己的 caller 推導迭代出兩個候選。

下游工具若拿 caller 名字做歸戶,等於每站點收到一真一假;ccodegraph 舊管線
靠 `attribute_src`(節點存在 + 行區間)過濾掉假的——**碰巧**存活,而
ctags 漏建節點時(巨集生成函式)反而是假名字存活(見 D17 記錄)。

## Bug 3:丟行(且壓縮/未壓縮丟的不一樣)

radius_das.c 內 `radius_msg_get_attr_ptr` 實際有 **8** 個呼叫站點
(crossref 記錄齊全:76/88/100/106/121/127/133/139),但:

- 對壓縮 crossref(預設)查 `-L3`:回 5 個站點(丟 100/106/121);
- 對 `-c` 未壓縮 crossref 查:回另一組(88 只剩單列、121 只剩單列,
  100/106 全丟)。

同一份語意、兩種編碼、兩種丟法——丟行發生在查詢端的跳讀掃描。
`-q` 倒排索引的查詢路徑則回**第三種**結果集(wpa 實測比線性掃描多
2,224 個真站點、又少 534 calls + 1,000 includes 真邊)——三條查詢
路徑互不一致,crossref 本身卻是一致的。

## 對本專案的影響與處置

- v1-v5 benchmark 的所有圖都以 `-L` 輸出為原料 → 帶著上述幻影。
  量化(wpa/redis 全量邊集 diff):D17 直讀後淨增 +2,397/+5,139 條
  真邊(丟行回收),移除的邊 100% 通過幻影判定。kernel 子樹:
  nodes/includes/callback/fnptr 與舊圖完全一致,calls/expands/reads/
  writes 淨增 +1,377/−22/+707/+86。
- 處置:D17 起 L1 不再經過 cscope 查詢端(`parse_cscope_crossref()`
  直讀;cscope 只負責建 crossref)。`-L` 僅存於降級路徑。
- 上游價值:三類 bug 的最小重現(本文案例)可回報 cscope 專案;
  對任何「用 cscope 當 oracle」的研究,這是方法論警訊——
  **oracle 也要驗**(本專案 v2-v5 的評分三課 + 本篇,同一個教訓的
  第四次出現:GT 會錯、評分者會信錯的 GT、評分者看到的 GT 視圖會被
  工程細節弄殘、oracle 工具自己有 bug)。

## 2026-07-21 更新:6 行自包含 repro + 根因定位(delta 最小化產物)

上游維護者回覆(質疑樹相依案例、指向 fn-ptr 方向)後,我們以
ddmin(檔案集二分 → 行級二分 → 消融)把 Class 1 收斂到 **6 行、
零依賴**:

```c
/* a.h */
void register_handler(RxResult (*handler)(void), void *data);
/* b.c */
static int dispatch(void)
{
	probe_call();
	return 0;
}
```

`-L3 probe_call` → b.c 的呼叫站點被雙報:caller=`dispatch`(正確)
+ caller=**`RxResult`**(只存在於 a.h 的型別名——跨檔幻影)。

**根因(cscope 自己的話)**:`-L1 RxResult` 顯示掃描器把 fn-ptr
參數宣告的**回傳型別**記成了**函式定義**;該幻影函式無配對 `}`,
範圍永不關閉,跨檔吞噬後續所有檔案的 caller 歸屬。消融:拿掉該
宣告行即全乾淨;單行/多行格式無關。**統一假說已證(2026-07-21,patch 驗收)**:Class 2 丟行與
Class 3 漂移確是同一「開放幻影範圍」的下游症狀——單一 fscanner.l
patch 在真實 wpa 樹上同時消除三者:雙報 caller 5→0、正確站點 5/8→8/8、
fst 檔案漂移(fst_internal.h:1255)消失、crossref 幻影標記 2→0。
patch 與回歸腳本(regress-306.sh:含多行變體 case1b)、化簡來源鏈見
`hard-benchmark/cscope-bugs/`。repro 檔:
`hard-benchmark/cscope-bugs/`;issue 討論:
<https://sourceforge.net/p/cscope/bugs/306/>。

## 復現指引

```bash
# Bug 1/2/3 的 wpa 復現(標準 checkout 即可):
cd wpa_supplicant-checkout
cscope -bckR -f /tmp/cs.out
cscope -d -f /tmp/cs.out -L3 radius_msg_get_attr_ptr   # Bug 2+3
cscope -d -f /tmp/cs.out -L3 os_free | grep crypto_internal  # Bug 1
# crossref 原始 bytes 對質(無 223 行記錄):
python3 -c "
data = open('/tmp/cs.out','rb').read()
i = data.find(b'\t@src/crypto/crypto_internal.c')
print(data[i:i+20000].decode('utf-8','replace'))" | grep -n '^22[0-9] '
```

差分測試器與逐案調查記錄:D17 開發過程(design.md §8.5.6);
kernel 規模驗收數字:research/llm-ab-v5-linux-kernel.md §4.1。
