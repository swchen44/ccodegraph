# GT — LKQ-049 (kconfig-build, L2)

## Question (verbatim)

"For the e1000e driver: (a) the Kconfig option that enables it — file:line of the config declaration; (b) the Makefile rule(s) compiling its objects — file:line of the obj-$(CONFIG_...) line and the object list; (c) explicitly enumerate ALL build-system gating layers: the driver-local Makefile line AND every parent-directory Makefile/Kconfig condition required for the build system to even descend into that directory (e.g. vendor-level config)."

## Ground Truth

Repo: Linux kernel v6.6 (`repos/linux-v6.6`). All lines verified at source on 2026-07-09.

### Part (a) — Kconfig declaration

- **`config E1000E`** — `drivers/net/ethernet/intel/Kconfig:58`
  ```
  58  config E1000E
  59      tristate "Intel(R) PRO/1000 PCI-Express Gigabit Ethernet support"
  60      depends on PCI && (!SPARC32 || BROKEN)
  61      depends on PTP_1588_CLOCK_OPTIONAL
  62      select CRC32
  ```
- The declaration sits inside the `if NET_VENDOR_INTEL` block (`drivers/net/ethernet/intel/Kconfig:17` … `endif # NET_VENDOR_INTEL` at line 359), so E1000E implicitly depends on `NET_VENDOR_INTEL` in addition to its explicit `depends on` lines.
- Do NOT confuse with `config E1000E_HWTS` at line 78 (a bool sub-option, `depends on E1000E && X86`) or `config E1000` at line 42 (the older PCI/PCI-X driver).

### Part (b) — Makefile rules compiling the objects

1. **Vendor-directory descent into the driver dir** — `drivers/net/ethernet/intel/Makefile:8`
   ```
   obj-$(CONFIG_E1000E) += e1000e/
   ```
2. **Driver-local module rule** — `drivers/net/ethernet/intel/e1000e/Makefile:11`
   ```
   obj-$(CONFIG_E1000E) += e1000e.o
   ```
3. **Object list (composite objects)** — `drivers/net/ethernet/intel/e1000e/Makefile:13-15`
   ```
   e1000e-objs := 82571.o ich8lan.o 80003es2lan.o \
                  mac.o manage.o nvm.o phy.o \
                  param.o ethtool.o netdev.o ptp.o
   ```
   11 objects: `82571.o ich8lan.o 80003es2lan.o mac.o manage.o nvm.o phy.o param.o ethtool.o netdev.o ptp.o`.

### Part (c) — ALL build-system gating layers

#### Makefile descent chain (bottom → top)

| Layer | File:Line | Exact line | Gating symbol |
|---|---|---|---|
| 1 (driver) | `drivers/net/ethernet/intel/e1000e/Makefile:11` | `obj-$(CONFIG_E1000E) += e1000e.o` | `CONFIG_E1000E` |
| 2 (vendor dir) | `drivers/net/ethernet/intel/Makefile:8` | `obj-$(CONFIG_E1000E) += e1000e/` | `CONFIG_E1000E` |
| 3 (ethernet dir) | `drivers/net/ethernet/Makefile:50` | `obj-$(CONFIG_NET_VENDOR_INTEL) += intel/` | `CONFIG_NET_VENDOR_INTEL` |
| 4 (net dir) | `drivers/net/Makefile:52` | `obj-$(CONFIG_ETHERNET) += ethernet/` | `CONFIG_ETHERNET` |
| 5 (drivers dir) | `drivers/Makefile:95` | `obj-y += net/` | **unconditional** (`obj-y`, NOT `obj-$(CONFIG_NET)` and NOT `obj-$(CONFIG_NETDEVICES)`) |
| 6 (top level) | `Kbuild:94` | `obj-y += drivers/` | **unconditional** (top-level `Kbuild`; the top `Makefile` only has empty `drivers-y :=` at Makefile:747 for arch add-ons) |

Key trap: descent into `drivers/net/` is **not** config-gated — `drivers/Makefile:95` is `obj-y += net/`. So `CONFIG_NETDEVICES` and `CONFIG_NET` gate the build only through the *Kconfig dependency chain* (they make `ETHERNET`/`NET_VENDOR_INTEL`/`E1000E` unselectable), never through a Makefile descent line.

#### Kconfig dependency/visibility chain (bottom → top)

| Symbol | Declared at | Key line(s) | How it gates E1000E |
|---|---|---|---|
| `E1000E` | `drivers/net/ethernet/intel/Kconfig:58` | `depends on PCI && (!SPARC32 \|\| BROKEN)` (l.60), `depends on PTP_1588_CLOCK_OPTIONAL` (l.61), `select CRC32` (l.62) | the driver option itself |
| `NET_VENDOR_INTEL` | `drivers/net/ethernet/intel/Kconfig:6` (`bool "Intel devices"`, `default y`) | `if NET_VENDOR_INTEL` block l.17–359 wraps E1000E | implicit `depends on NET_VENDOR_INTEL` |
| `ETHERNET` | `drivers/net/ethernet/Kconfig:6` (`menuconfig ETHERNET`) | `depends on NET` (l.8), `default y`; `if ETHERNET` block l.13–196 wraps `source "drivers/net/ethernet/intel/Kconfig"` (l.86) | intel/Kconfig is sourced inside `if ETHERNET` |
| `NETDEVICES` | `drivers/net/Kconfig:6` (`menuconfig NETDEVICES`) | `depends on NET` (l.8); `if NETDEVICES` block l.27–647 wraps `source "drivers/net/ethernet/Kconfig"` (l.490) | ethernet/Kconfig is sourced inside `if NETDEVICES` |
| `NET` | `net/Kconfig:6` (`menuconfig NET`, `bool "Networking support"`) | sourced from top-level `Kconfig:18` | required by both `NETDEVICES` and `ETHERNET` |
| `PCI` | `drivers/pci/Kconfig:16` (`menuconfig PCI`, `depends on HAVE_PCI`) | sourced from `drivers/Kconfig:8` | explicit `depends on PCI` at intel/Kconfig:60 |
| `PTP_1588_CLOCK_OPTIONAL` | `drivers/ptp/Kconfig:30` (`tristate`, `default y if PTP_1588_CLOCK=n`, `default PTP_1588_CLOCK`) | always met (dummy helpers if PTP off); prevents E1000E=y with PTP_1588_CLOCK=m | explicit dependency at intel/Kconfig:61 |

Kconfig sourcing chain (for completeness): top `Kconfig:20` → `drivers/Kconfig:54` (`source "drivers/net/Kconfig"`) → `drivers/net/Kconfig:490` → `drivers/net/ethernet/Kconfig:86` → `drivers/net/ethernet/intel/Kconfig`.

### Minimal complete gating summary

For `e1000e.o` objects to be compiled, ALL of the following must hold:
1. `CONFIG_E1000E=y|m` — which via Kconfig requires `NET_VENDOR_INTEL` (default y), `ETHERNET` (default y), `NETDEVICES`, `NET`, `PCI` (thus `HAVE_PCI`), `PTP_1588_CLOCK_OPTIONAL` (always satisfiable), and not (`SPARC32` without `BROKEN`).
2. Makefile descent: `Kbuild:94` (obj-y, unconditional) → `drivers/Makefile:95` (obj-y, unconditional) → `drivers/net/Makefile:52` (`CONFIG_ETHERNET`) → `drivers/net/ethernet/Makefile:50` (`CONFIG_NET_VENDOR_INTEL`) → `drivers/net/ethernet/intel/Makefile:8` (`CONFIG_E1000E`) → `drivers/net/ethernet/intel/e1000e/Makefile:11,13-15`.

## Question-text check

No blocking defects; two grader-relevant nuances:
1. The exemplar in the prompt hints "drivers/net/Makefile (`obj-$(CONFIG_ETHERNET)` — verify)" and "drivers/Makefile net entry — obj-y or obj-$(CONFIG_NET)?". Verified answers: `CONFIG_ETHERNET` is correct (drivers/net/Makefile:52); the drivers/Makefile entry is **`obj-y += net/`** (line 95) — an answer claiming `obj-$(CONFIG_NET)` or `obj-$(CONFIG_NETDEVICES)` there is factually wrong.
2. "ALL build-system gating layers" is satisfiable but open-ended at the top: the deepest layer is top-level `Kbuild:94` (`obj-y += drivers/`). Since layers 5–6 are unconditional `obj-y`, a defensible answer may state that the *conditional* gating layers are exactly: E1000E (×2 Makefiles), NET_VENDOR_INTEL, ETHERNET — plus the Kconfig-only gates NETDEVICES/NET/PCI. Do not penalize omission of the unconditional Kbuild/drivers layers if the answer explicitly notes descent to drivers/net/ is unconditional.

## Rubric (0-3)

- **3** — (a) `drivers/net/ethernet/intel/Kconfig:58` (±2 lines, must name file exactly) AND (b) both `intel/Makefile:8` (`obj-$(CONFIG_E1000E) += e1000e/`) and `e1000e/Makefile:11` + object list at 13-15 (all 11 objects or the `e1000e-objs :=` line cited) AND (c) at least 2 parent gating layers named correctly with their symbols (`NET_VENDOR_INTEL` @ ethernet/Makefile:50 and `ETHERNET` @ net/Makefile:52; credit also Kconfig-side NETDEVICES/NET/PCI if tied to correct declaration sites). No false claims (e.g. asserting `obj-$(CONFIG_NET)` in drivers/Makefile is an error that caps at 2).
- **2** — (a) and (b) exact (correct files + lines/content), but fewer than 2 parent gating layers correctly identified, or parent layers named without file:line evidence.
- **1** — Partial: correct Kconfig option and driver Makefile located but wrong/missing lines, or object list incomplete, or only vendor Makefile found.
- **0** — Wrong files/symbols (e.g. confusing E1000 with E1000E, or citing E1000E_HWTS as the driver option).
