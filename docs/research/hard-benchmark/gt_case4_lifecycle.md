# GT case 4: createStringObject* lifecycle in src/t_string.c (redis)

Method: grep 全部 createStringObject*/decrRefCount 呼叫點,用 ccodegraph 的
nodes(file,line_start,line_end) 把每個站點對應到 enclosing function,人工讀函式體判斷
「本函式內配對釋放」vs「所有權轉移(交給 DB,不在本函式釋放)」。

## 本函式內配對釋放(locally freed — clean lifecycle)

| enclosing function | alloc line | alloc call | free line |
|---|---|---|---|
| setGenericCommand | 197 | createStringObjectFromLongLong | 207 |
| getexCommand | 541 | createStringObjectFromLongLong | 543 |
| msetexCommand | 891 | createStringObjectFromLongLong | 894 |
| increxCommand | 1345 | createStringObjectFromLongLong | 1347 |
| lcsCommand | 1439/1440 | createStringObject("",0) | 1629/1630 |

## 所有權轉移(ownership transfer — 不在本函式釋放,交給 DB 之後由 overwrite/expire/del 路徑釋放)

| enclosing function | alloc line | alloc call | 去向 |
|---|---|---|---|
| incrDecrCommand | 926 | createStringObjectFromLongLongForValue | 成為新值,交給 setKeyByLink/dbAdd 系列 |
| incrbyfloatCommand | 983 | createStringObjectFromLongDouble | 同上 |
| increxCommand | 1323/1325 | createStringObjectFromLongDouble / createStringObjectFromLongLongForValue | 同上 |

**評分關鍵**:能否正確區分這兩類(不是「有沒有找到 create/decrRefCount」,是「有沒有正確
判斷哪些有所有權轉移」)。grep 找 create/decrRefCount 呼叫點本身不難;難的是判斷
incrDecrCommand/incrbyfloatCommand/increxCommand 這三個函式裡的 new 物件**沒有**局部
decrRefCount 是因為所有權轉移,而不是記憶體洩漏或工具漏抓。
