# GT WRQ-015: .c files that directly #include "eloop.h"

**Category**: include-dependency | **Difficulty**: L2

## Question (verbatim)

> Which .c files directly #include "eloop.h"? Give an exact count and confirm whether the
> count matches a transitive closure via any header that itself includes eloop.h.

Scope check: the question does not say "in src/" or "in wpa_supplicant/" — it says ".c files"
with no directory restriction. The whole repo was searched (`src/`, `wpa_supplicant/`, `hs20/`,
`patches/`), not just `src/`. This reading was deliberately double-checked before answering.

## Method

1. `grep -rl --include='*.c' '#include "eloop.h"' .` from the repo root — literal, bare-name
   include form. **59 files.**
2. Cross-checked with `find . -name '*.c' -print0 | xargs -0 grep -l '#include "eloop.h"' | wc -l`
   — also 59. Counts agree.
3. **Build-system-level check (the trap):** a plain literal-string grep for `#include "eloop.h"`
   is not the whole picture, because the physical header can be spelled two ways depending on
   which include path resolves it. Searched for the alternate spelling:
   `grep -rl --include='*.c' '#include "utils/eloop.h"' .` → **58 more files**, with **zero
   overlap** with the 59 bare-form files (`comm -12` on the two sorted lists is empty).
   Confirmed there is only one physical `eloop.h` in the repo: `src/utils/eloop.h`
   (`find . -name eloop.h` → single hit).
4. Confirmed both spellings are real, build-reachable includes, not dead code: `wpa_supplicant/Makefile`
   lines 15-16 set `CFLAGS += -I$(abspath ../src)` and `CFLAGS += -I$(abspath ../src/utils)`
   **unconditionally** (outside any `ifdef`, evaluated for every build). With both `-I../src`
   and `-I../src/utils` on the search path, `#include "eloop.h"` and `#include "utils/eloop.h"`
   both resolve to the identical file `src/utils/eloop.h`. The 58 "utils/eloop.h"-form files are
   overwhelmingly in `src/ap/*.c` (hostapd-side AP code, pulled into the wpa_supplicant build via
   `OBJS += ../src/ap/hostapd.o`, `.../sta_info.o`, etc. under `ifdef CONFIG_AP`, itself default-on
   in common `.config` combinations such as `CONFIG_MESH=y`), plus a handful of `src/utils/*.c`,
   `src/crypto/random.c`, `src/drivers/driver_nl80211_{event,monitor,scan}.c`,
   `src/drivers/rfkill.c`, `src/fst/*.c`, `src/pae/ieee802_1x_{cp,secy_ops}.c`,
   `src/radius/radius_das.c`, `src/rsn_supp/tdls.c`, `src/p2p/p2p_go_neg.c`, and several
   `wpa_supplicant/*.c` files (`ap.c`, `bss.c`, `scan.c`, `sme.c`, `mesh*.c`, `ctrl_iface*.c`,
   `dbus/*.c`, `gas_query.c`, `ibss_rsn.c`, `interworking.c`, `offchannel.c`, `wmm_ac.c`,
   `wpa_cli.c`).
5. Searched every header for either include form:
   `grep -rl --include='*.h' '#include "eloop.h"' .` → **0 hits**.
   `grep -rl --include='*.h' '#include "utils/eloop.h"' .` → **0 hits**.
   Broadest possible net, `grep -rln 'eloop\.h' --include='*.h' .` → **0 hits**.
   **No header file in the repository includes eloop.h in any form**, so there is no header
   that could pull eloop.h into a `.c` file transitively.

## Result

- **Literal/naive count (bare `#include "eloop.h"` string only): 59 files.**
- **True direct-include count (either valid spelling of the same physical header,
  build-verified): 117 files** = 59 (bare `"eloop.h"`) + 58 (`"utils/eloop.h"`), no overlap.
- **Transitive closure via headers: empty set (0 headers re-export eloop.h).** Since no `.h`
  file anywhere in the tree includes eloop.h, no `.c` file can be pulling it in only
  transitively through a header. Every `.c` file that depends on eloop.h must and does include
  it directly (in one of the two spellings) — the direct-include set already is the full
  dependency set; the transitive closure adds **zero** additional files. In that sense "the
  count matches the transitive closure" is **true but only because the transitive contribution
  is empty**, not because it was double-counted or reconciled against overlap.

### Full file lists

**Form A — bare `#include "eloop.h"` (59):**
`src/drivers/driver_atheros.c`, `src/drivers/driver_bsd.c`, `src/drivers/driver_hostap.c`,
`src/drivers/driver_ndis_.c`, `src/drivers/driver_ndis.c`, `src/drivers/driver_nl80211.c`,
`src/drivers/driver_privsep.c`, `src/drivers/driver_wext.c`, `src/drivers/driver_wired.c`,
`src/drivers/netlink.c`, `src/eap_peer/eap_vendor_test.c`, `src/eap_server/eap_server_wsc.c`,
`src/eap_server/eap_sim_db.c`, `src/eapol_auth/eapol_auth_sm.c`, `src/eapol_supp/eapol_supp_sm.c`,
`src/l2_packet/l2_packet_freebsd.c`, `src/l2_packet/l2_packet_linux.c`,
`src/l2_packet/l2_packet_ndis.c`, `src/l2_packet/l2_packet_none.c`,
`src/l2_packet/l2_packet_pcap.c`, `src/l2_packet/l2_packet_privsep.c`,
`src/l2_packet/l2_packet_winpcap.c`, `src/p2p/p2p.c`, `src/pae/ieee802_1x_kay.c`,
`src/radius/radius_client.c`, `src/radius/radius_server.c`, `src/rsn_supp/peerkey.c`,
`src/rsn_supp/pmksa_cache.c`, `src/rsn_supp/preauth.c`, `src/rsn_supp/wpa.c`,
`src/utils/edit_readline.c`, `src/utils/edit_simple.c`, `src/utils/edit.c`,
`src/utils/eloop_win.c`, `src/utils/eloop.c`, `src/wps/http_client.c`, `src/wps/http_server.c`,
`src/wps/httpread.c`, `src/wps/wps_er_ssdp.c`, `src/wps/wps_er.c`, `src/wps/wps_upnp_ap.c`,
`src/wps/wps_upnp_event.c`, `src/wps/wps_upnp_ssdp.c`, `wpa_supplicant/bgscan_learn.c`,
`wpa_supplicant/bgscan_simple.c`, `wpa_supplicant/ctrl_iface_named_pipe.c`,
`wpa_supplicant/ctrl_iface_udp.c`, `wpa_supplicant/dbus/dbus_old.c`,
`wpa_supplicant/eapol_test.c`, `wpa_supplicant/events.c`, `wpa_supplicant/hs20_supplicant.c`,
`wpa_supplicant/main_winsvc.c`, `wpa_supplicant/p2p_supplicant.c`,
`wpa_supplicant/preauth_test.c`, `wpa_supplicant/tests/test_wpa.c`, `wpa_supplicant/wpa_priv.c`,
`wpa_supplicant/wpa_supplicant.c`, `wpa_supplicant/wpas_glue.c`,
`wpa_supplicant/wps_supplicant.c`.

**Form B — `#include "utils/eloop.h"` (58, same physical header, zero overlap with Form A):**
`src/ap/accounting.c`, `src/ap/ap_list.c`, `src/ap/bss_load.c`, `src/ap/drv_callbacks.c`,
`src/ap/gas_serv.c`, `src/ap/hostapd.c`, `src/ap/hw_features.c`, `src/ap/iapp.c`,
`src/ap/ieee802_11_auth.c`, `src/ap/ieee802_11_ht.c`, `src/ap/ieee802_11.c`,
`src/ap/ieee802_1x.c`, `src/ap/peerkey_auth.c`, `src/ap/pmksa_cache_auth.c`,
`src/ap/preauth_auth.c`, `src/ap/sta_info.c`, `src/ap/tkip_countermeasures.c`,
`src/ap/vlan_init.c`, `src/ap/vlan_util.c`, `src/ap/wnm_ap.c`, `src/ap/wpa_auth_ft.c`,
`src/ap/wpa_auth.c`, `src/ap/wps_hostapd.c`, `src/crypto/random.c`,
`src/drivers/driver_macsec_qca.c`, `src/drivers/driver_nl80211_event.c`,
`src/drivers/driver_nl80211_monitor.c`, `src/drivers/driver_nl80211_scan.c`,
`src/drivers/rfkill.c`, `src/fst/fst_session.c`, `src/fst/fst.c`, `src/p2p/p2p_go_neg.c`,
`src/pae/ieee802_1x_cp.c`, `src/pae/ieee802_1x_secy_ops.c`, `src/radius/radius_das.c`,
`src/rsn_supp/tdls.c`, `src/utils/browser-android.c`, `src/utils/browser-system.c`,
`src/utils/browser-wpadebug.c`, `src/utils/utils_module_tests.c`, `src/wps/wps_registrar.c`,
`wpa_supplicant/ap.c`, `wpa_supplicant/bss.c`, `wpa_supplicant/ctrl_iface_unix.c`,
`wpa_supplicant/ctrl_iface.c`, `wpa_supplicant/dbus/dbus_common.c`,
`wpa_supplicant/dbus/dbus_new_helpers.c`, `wpa_supplicant/gas_query.c`,
`wpa_supplicant/ibss_rsn.c`, `wpa_supplicant/interworking.c`, `wpa_supplicant/mesh_mpm.c`,
`wpa_supplicant/mesh_rsn.c`, `wpa_supplicant/mesh.c`, `wpa_supplicant/offchannel.c`,
`wpa_supplicant/scan.c`, `wpa_supplicant/sme.c`, `wpa_supplicant/wmm_ac.c`,
`wpa_supplicant/wpa_cli.c`.

## Scoring rubric (0-3)

- **3**: States the count is **59** for a literal bare-string `#include "eloop.h"` grep, **and**
  independently surfaces the `"utils/eloop.h"` alternate spelling (58 more files, same physical
  `src/utils/eloop.h`, zero overlap, verified build-reachable via wpa_supplicant/Makefile's
  unconditional `-I../src`/`-I../src/utils` CFLAGS), giving a true direct-include total of
  **117**, AND correctly reports that **zero headers** include eloop.h (so the transitive
  closure contributes nothing beyond the direct set — the "match" holds trivially because the
  transitive-only contribution is empty, not because of any cancellation).
- **2**: Reports 59 as the direct-include count with correct methodology and correctly finds
  zero transitive-including headers (so concludes "count matches" is vacuously true), but does
  **not** notice/mention the `"utils/eloop.h"` alternate-spelling files that also directly
  depend on eloop.h — i.e., treats 59 as the final true count rather than a lower bound of a
  literal string search.
- **1**: Gets a substantially correct count (e.g., 59, or 117 without band-verifying zero
  overlap/build reachability) but mishandles the transitive-closure question — e.g., claims some
  header includes eloop.h without verifying, or fails to check headers at all and just asserts
  "yes it matches" with no evidence.
- **0**: Wrong count (off by more than a handful with no defensible methodology), scope creep/
  shrinkage (e.g., only searched `src/` or only `wpa_supplicant/` and reported that partial count
  as the total), or fabricated header names claimed to include eloop.h.
