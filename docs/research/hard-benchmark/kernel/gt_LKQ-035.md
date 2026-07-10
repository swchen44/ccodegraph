# GT — LKQ-035 (callback-indirect, L3)

## Question (verbatim)

"In the e1000e driver (drivers/net/ethernet/intel/e1000e/): find the struct net_device_ops instance — variable name and file:line; the function assigned to .ndo_start_xmit (name + definition file:line); and the registration path: which function assigns this ops struct to netdev->netdev_ops (file:line)."

Repo: Linux kernel v6.6 (verified `git describe` = v6.6). All paths relative to repo root; all line numbers verified by direct read.

## Answer

All three pieces live in a single file: `drivers/net/ethernet/intel/e1000e/netdev.c`.

### 1. The net_device_ops instance

**`e1000e_netdev_ops`** — `drivers/net/ethernet/intel/e1000e/netdev.c:7327` (struct literal spans 7327-7347, closing `};` at 7347).

```c
static const struct net_device_ops e1000e_netdev_ops = {    /* netdev.c:7327 */
	.ndo_open		= e1000e_open,                          /* netdev.c:7328 */
	.ndo_stop		= e1000e_close,                         /* netdev.c:7329 */
	.ndo_start_xmit		= e1000_xmit_frame,                 /* netdev.c:7330 */
```

### 2. .ndo_start_xmit handler

**`e1000_xmit_frame`**, assigned at `netdev.c:7330` (quoted above); defined at `drivers/net/ethernet/intel/e1000e/netdev.c:5781` (signature spans 5781-5782, body opens 5783):

```c
static netdev_tx_t e1000_xmit_frame(struct sk_buff *skb,    /* netdev.c:5781 */
				    struct net_device *netdev)               /* netdev.c:5782 */
{
```

Note: it is `static`, so it exists only in netdev.c; no other definition or reference in the driver directory. (The legacy e1000 driver has its own distinct `e1000_xmit_frame` in drivers/net/ethernet/intel/e1000/ — out of scope; citing that file is wrong.)

### 3. Registration site

Inside **`e1000_probe`** (definition at `drivers/net/ethernet/intel/e1000e/netdev.c:7360`):

```c
static int e1000_probe(struct pci_dev *pdev, const struct pci_device_id *ent)  /* netdev.c:7360 */
```

the assignment is at `drivers/net/ethernet/intel/e1000e/netdev.c:7451`:

```c
	/* construct the net_device struct */                    /* netdev.c:7450 */
	netdev->netdev_ops = &e1000e_netdev_ops;                 /* netdev.c:7451 */
	e1000e_set_ethtool_ops(netdev);                          /* netdev.c:7452 */
```

Enclosing-function verification: `e1000_probe` opens at 7360 and no function-closing `}` at column 0 occurs between 7360 and 7451, so line 7451 is inside `e1000_probe`.

Registration-path context (bonus precision, not required): `e1000_probe` is the PCI probe callback — `.probe = e1000_probe` in `static struct pci_driver e1000_driver` at `netdev.c:7943` — and later in the same probe function `register_netdev(netdev)` is called at `netdev.c:7678`, publishing the ops.

## Completeness check

`grep -rn "netdev_ops" drivers/net/ethernet/intel/e1000e/` yields exactly two hits: the definition (netdev.c:7327) and the assignment (netdev.c:7451). There is **no second `struct net_device_ops` instance** anywhere in the driver directory, and no other assignment to `netdev->netdev_ops`. The answer is unique.

## Question-text check

No defects. The presumed variable name `e1000e_netdev_ops` is exact; `.ndo_start_xmit = e1000_xmit_frame` is exact; the assignment is genuinely inside `e1000_probe`. One trap for tools/answers: the near-identical legacy driver `drivers/net/ethernet/intel/e1000/e1000_main.c` has its own `e1000_netdev_ops` (no second "e") with its own `e1000_xmit_frame` — the scope limiter "drivers/net/ethernet/intel/e1000e/" must be honored literally.

## Rubric (0-3)

- **3** — All three correct with file:line evidence: (a) `e1000e_netdev_ops` at netdev.c:7327; (b) `e1000_xmit_frame` assigned at netdev.c:7330, defined at netdev.c:5781; (c) registration inside `e1000_probe` at netdev.c:7451. Small line drift (±5) acceptable. Stating there is only one ops instance, or the pci_driver `.probe` context, is bonus precision, not required.
- **2** — Ops struct (name + location) and xmit handler (name + definition) both correct, but the registration site is missing or wrong (e.g. names a function other than `e1000_probe`, cites `register_netdev` instead of the netdev_ops assignment, or gives no file:line for the assignment).
- **1** — Only one piece correct (e.g. names `e1000e_netdev_ops` but wrong/absent xmit definition line and no registration site; or finds `e1000_xmit_frame` only).
- **0** — Wrong driver directory (e.g. legacy e1000's `e1000_netdev_ops` / `e1000_main.c`), hallucinated names/lines, or no verifiable evidence.

Scoring note: answers citing the legacy e1000 driver's symbols for any piece score that piece as wrong — the scope limiter is literal.


## SUBTREE ADDENDUM(2026-07-10)

執行樹為 8,170 檔子樹:legacy e1000 driver 目錄(drivers/net/ethernet/intel/
e1000/)**不在樹內**,原 GT 的「legacy driver 混淆陷阱」在此輪不會發作。
其餘答案(e1000e_netdev_ops netdev.c:7327、e1000_xmit_frame :5781/:7330、
註冊 :7451)不受影響。