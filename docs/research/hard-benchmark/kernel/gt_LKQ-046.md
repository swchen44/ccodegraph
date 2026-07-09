# GT — LKQ-046 (data-structure, L2)

## Question (verbatim)

"In struct net_device (include/linux/netdevice.h), identify the field that points to the device operations table (struct net_device_ops): field name + line number inside the struct definition. Then show one real call site in net/core/dev.c where a callback is invoked through this field (file:line + which ndo_* callback)."

## Ground Truth

Repo: Linux kernel v6.6 (`repos/linux-v6.6`). All lines verified at source on 2026-07-09.

### Part 1 — Field

- **Field name:** `netdev_ops`
- **Declaration:** `include/linux/netdevice.h:2092`
  ```c
  const struct net_device_ops *netdev_ops;
  ```
- Context: inside `struct net_device` (struct definition starts at `include/linux/netdevice.h:2056`), in the "Read-mostly cache-line for fast-path access" block.
- The kerneldoc comment for the field is at line 1835 (`@netdev_ops: Includes several pointers to callbacks, ...`) — this is documentation, NOT the field declaration. Only 2092 is the line "inside the struct definition".

### Part 2 — Call sites in net/core/dev.c (any ONE valid site earns full credit)

**Group A — direct `dev->netdev_ops->ndo_*(...)` invocations (preferred answers):**

| # | net/core/dev.c line(s) | ndo_* callback | Enclosing function |
|---|------------------------|----------------|--------------------|
| 1 | 655 | `ndo_get_iflink` | `dev_get_iflink()` (fn at 649) |
| 2 | 683 | `ndo_fill_metadata_dst` | `dev_fill_metadata_dst()` (fn at 670) |
| 3 | 716 | `ndo_fill_forward_path` | `dev_fill_forward_path()` (fn at 697) |
| 4 | 3553 (stmt spans 3553–3554) | `ndo_features_check` | `netif_skb_features()` (fn at 3531) |
| 5 | 4533 (stmt spans 4533–4534) | `ndo_rx_flow_steer` | `set_rps_cpu()` (fn at 4508) |
| 6 | 9812 | `ndo_fix_features` | `__netdev_update_features()` (fn at 9800) |
| 7 | 9828 | `ndo_set_features` | `__netdev_update_features()` (fn at 9800) |
| 8 | 10096 | `ndo_init` | `register_netdevice()` (fn at 10062) |
| 9 | 10223 | `ndo_uninit` | `register_netdevice()` err_uninit path |
| 10 | 10987 | `ndo_uninit` | `unregister_netdevice_many_notify()` (fn at 10908) |

**Group B — invocation through a local `const struct net_device_ops *ops = dev->netdev_ops;` alias (also acceptable — still dispatch through the `netdev_ops` field):**

| # | net/core/dev.c line(s) | ndo_* callback | Enclosing function (alias assignment line) |
|---|------------------------|----------------|--------------------------------------------|
| 11 | 1472 | `ndo_validate_addr` | `__dev_open()` (ops at 1444) |
| 12 | 1475 | `ndo_open` | `__dev_open()` (ops at 1444) |
| 13 | 1559 | `ndo_stop` | `__dev_close_many()` (ops at 1549) |
| 14 | 4245 | `ndo_select_queue` | `netdev_pick_tx()` (ops at 4242) |
| 15 | 8390 | `ndo_change_rx_flags` | `dev_change_rx_flags()` (fn at 8385, ops at 8387) |
| 16 | 8547 | `ndo_set_rx_mode` | `__dev_set_rx_mode()` (fn at 8522) |
| 17 | 8713 | `ndo_change_mtu` | `__dev_set_mtu()` (fn at 8708) |
| 18 | 8884 | `ndo_set_mac_address` | `dev_set_mac_address()` (fn at 8868) |
| 19 | 8952 | `ndo_change_carrier` | `dev_change_carrier()` (fn at 8944) |

Notes:
- Guard-only lines (e.g. 654 `if (dev->netdev_ops && dev->netdev_ops->ndo_get_iflink)`, 3552, 9113, 9123, 10095, 10106–10107, 10222, 10986) test the pointer but do not invoke it. The invocation lines are those in the tables. Accept an answer citing the guard line ±1 if it names the correct callback and the invocation is on the adjacent line.
- `ops->ndo_start_xmit` is invoked via `netdev_start_xmit()` in include/linux/netdevice.h (line ~4926, `__netdev_start_xmit`), NOT in net/core/dev.c — an answer citing ndo_start_xmit "in dev.c" is wrong on file scope (dev.c only takes `ops = dev->netdev_ops` at 4876/4900 in xmit helpers and passes it along; the actual `ops->ndo_start_xmit(...)` call is in the header).
- `ndo_do_ioctl` sites are in net/core/dev_ioctl.c — out of scope per the question's "net/core/dev.c" limiter.

## Question-text check

No defects. The file scope ("net/core/dev.c") and struct scope ("inside the struct definition") are both unambiguous and satisfiable. One nuance for graders: the most famous callback (`ndo_start_xmit`) is invoked from netdevice.h, not dev.c — a common wrong answer.

## Rubric (0–3)

- **3** — Field `netdev_ops` + line 2092 (accept 2090–2094 if the answer shows the exact declaration text) AND one valid dev.c invocation site: correct line (±2 tolerance for guard/continuation lines) + correct ndo_* callback name, from Group A or B (or any other verified `->ndo_*(...)` invocation through `netdev_ops` in dev.c).
- **2** — Field name + line correct, but call site flawed: wrong line for a real callback, callback invoked via header/other file (e.g. ndo_start_xmit in netdevice.h) cited as dev.c, or guard line cited with wrong callback name. OR: valid call site but field line wrong/missing (e.g. cites kerneldoc line 1835).
- **1** — Only the field name `netdev_ops` correct (no usable line, no valid site), or only a valid site without identifying the field.
- **0** — Wrong field (e.g. `ethtool_ops`, `xdp_metadata_ops`), or no verifiable content.
