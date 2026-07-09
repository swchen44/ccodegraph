# GT — LKQ-057 (include-dependency, L2)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`)
**Verified:** 2026-07-09, two independent methods, agreement confirmed.

## Question (verbatim)

> "Find the header defining struct sk_buff (file + line of the struct definition). Then count the .c files directly under net/core/ (that single directory, not recursive) that directly #include that header by any spelling, list them, and give the exact count. Cross-check the count with a second method."

## Answer

### 1. Header site

`struct sk_buff` is defined in **`include/linux/skbuff.h`, line 842** (`struct sk_buff {`).

- Uniqueness verified: `grep -rn --include='*.h' '^struct sk_buff {' include/` yields exactly one hit (skbuff.h:842). Kernel-wide there is no second definition of the struct; other files only carry forward declarations (`struct sk_buff;`).

### 2. Direct includers in net/core/ (single directory, not recursive)

Population: `net/core/` contains **56** `.c` files directly (no recursion into subdirectories — net/core has none containing .c files that would confuse the scope, but graders must not recurse regardless).

**Exact count: 21** `.c` files directly `#include` the header.

Include-spelling audit (lesson from prior round applied): a broad sweep
`grep -nE '^[[:space:]]*#[[:space:]]*include[[:space:]]*[<"][^">]*skbuff[^">]*[">]' net/core/*.c`
catches every spelling — angle-bracket, quoted, `#include<` without space, `# include`, and any path variant containing "skbuff". Result: **all 21 hits use the single canonical spelling `#include <linux/skbuff.h>`**; no quoted (`"linux/skbuff.h"`), relative-path, or whitespace-variant spellings exist in this directory. So "any spelling" collapses to the canonical one here.

The 21 includers (with the include's line number):

| # | File | Line |
|---|------|------|
| 1 | net/core/datagram.c | 57 |
| 2 | net/core/dev.c | 93 |
| 3 | net/core/dst.c | 18 |
| 4 | net/core/filter.c | 38 |
| 5 | net/core/flow_dissector.c | 3 |
| 6 | net/core/gen_estimator.c | 27 |
| 7 | net/core/gro_cells.c | 2 |
| 8 | net/core/gso.c | 2 |
| 9 | net/core/hwbm.c | 10 |
| 10 | net/core/lwt_bpf.c | 8 |
| 11 | net/core/lwtunnel.c | 14 |
| 12 | net/core/netprio_cgroup.c | 15 |
| 13 | net/core/pktgen.c | 137 |
| 14 | net/core/ptp_classifier.c | 98 |
| 15 | net/core/rtnetlink.c | 30 |
| 16 | net/core/scm.c | 33 |
| 17 | net/core/skbuff.c | 53 |
| 18 | net/core/skmsg.c | 5 |
| 19 | net/core/sock_diag.c | 6 |
| 20 | net/core/sock.c | 125 |
| 21 | net/core/timestamping.c | 10 |

### 3. Non-includers (grading note: transitive inclusion)

The remaining **35** `.c` files do NOT directly include `linux/skbuff.h`, even though many of them use `struct sk_buff` heavily — they get the header **transitively**. Prominent examples an answerer might wrongly count as direct includers:

- `net/core/gro.c` — gets it via `#include <net/gro.h>` (include/net/gro.h includes `<linux/skbuff.h>`)
- `net/core/neighbour.c` — via `#include <linux/netdevice.h>` (netdevice.h includes `<linux/skbuff.h>`)
- `net/core/netpoll.c`, `net/core/page_pool.c`, `net/core/xdp.c`, `net/core/sock_map.c`, `net/core/drop_monitor.c`, `net/core/dev_ioctl.c`, `net/core/flow_offload.c`, `net/core/request_sock.c` — all transitive only.

Full non-includer list (35): bpf_sk_storage.c, dev_addr_lists_test.c, dev_addr_lists.c, dev_ioctl.c, drop_monitor.c, dst_cache.c, failover.c, fib_notifier.c, fib_rules.c, flow_offload.c, gen_stats.c, gro.c, link_watch.c, neighbour.c, net_namespace.c, net-procfs.c, net-sysfs.c, net-traces.c, netclassid_cgroup.c, netdev-genl-gen.c, netdev-genl.c, netevent.c, netpoll.c, of_net.c, page_pool.c, request_sock.c, secure_seq.c, selftests.c, sock_map.c, sock_reuseport.c, stream.c, sysctl_net_core.c, tso.c, utils.c, xdp.c.

(21 + 35 = 56 = total .c files; partition verified.)

### 4. Two-method cross-check

- **Method A (grep -l):**
  `grep -lE '^[[:space:]]*#[[:space:]]*include[[:space:]]*[<"]linux/skbuff\.h[">]' net/core/*.c | wc -l` → **21**
- **Method B (per-file loop):**
  `for f in net/core/*.c; do grep -qE '...same pattern...' "$f" && n=$((n+1)); done` → **21**
- **Agreement: 21 = 21.** Additionally the broad "any path containing skbuff" sweep also returns the same 21 files, confirming no alternate spelling was missed.

## Question-text notes

- No defects found. The scope limiter ("that single directory, not recursive") is unambiguous; net/core/ has 56 direct .c files. "By any spelling" is answerable and was audited: only the canonical `<linux/skbuff.h>` spelling occurs.
- Trap the question is designed to catch: counting recursively (would pull in nothing extra here since net/core has no .c subdirectories in v6.6 — but graders should still check the answerer's method), or counting files that merely *use* sk_buff (transitive includers like gro.c/neighbour.c), which would inflate the count well past 21.

## Rubric (0–3)

- **3** — Header site correct (`include/linux/skbuff.h`, line 842; line within ±2 acceptable if the file is right and `struct sk_buff {` is identified) **and** exact count 21 **and** the includer list matches (no missing/extra files).
- **2** — Header file correct and count within ±2 of 21 (19–23), e.g., minor list errors; or exact count with a slightly wrong/missing line number and an otherwise correct list.
- **1** — Counted recursively / counted transitive includers (wrong methodology but engaged with the right header), or identified a wrong header while producing a plausible directory scan.
- **0** — Wrong header and wrong count, or no verifiable method.
