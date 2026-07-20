#!/bin/bash
# regress-306.sh <cscope-binary> — regression check for sf bug #306
# (function-pointer declarator wrongly recorded as a function definition).
# cscope 15.9 ships no test suite (make check is empty), so this is a
# minimal standalone harness. Exit 0 = all pass.
set -u
CS="${1:-cscope}"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
cd "$T"
fail=0
say(){ printf '%-42s %s\n' "$1" "$2"; }

# --- Case 1: the bug. fn-ptr param must NOT create a phantom definition
cat > a.h <<'H'
void register_handler(RxResult (*handler)(void), void *data);
H
cat > b.c <<'C'
static int dispatch(void)
{
	probe_call();
	return 0;
}
C
"$CS" -bk a.h b.c -f cs.out >/dev/null 2>&1
dup=$("$CS" -d -f cs.out -L3 probe_call | grep -c ' RxResult ')
l1=$("$CS" -d -f cs.out -L1 RxResult | wc -l | tr -d ' ')
if [ "$dup" = 0 ] && [ "$l1" = 0 ]; then say "case1 fn-ptr phantom" "PASS"; else say "case1 fn-ptr phantom" "FAIL (dup=$dup l1=$l1)"; fail=1; fi

# --- Case 1b: multi-line fn-ptr declaration (minimized from
# radius_client.h:237-243) must also stay clean
cat > e.h <<'H'
struct data;
int reg(struct data *d, int type,
	RxResult (*handler)
	(struct msg *m, void *ctx),
	void *arg);
H
"$CS" -bk e.h b.c -f cs1b.out >/dev/null 2>&1
ph=$(od -c cs1b.out 2>/dev/null | grep -c '$   R   x   R   e   s')
if [ "$ph" = 0 ]; then say "case1b multi-line fn-ptr" "PASS"; else say "case1b multi-line fn-ptr" "FAIL (phantom marks=$ph)"; fail=1; fi

# --- Case 2: ordinary function def must still be detected
cat > c.c <<'C'
int normal_func(int a, int b) { return a + b; }
static void caller(void) { normal_func(1, 2); }
C
"$CS" -bk c.c -f cs2.out >/dev/null 2>&1
d=$("$CS" -d -f cs2.out -L1 normal_func | wc -l | tr -d ' ')
call=$("$CS" -d -f cs2.out -L3 normal_func | grep -c 'caller')
if [ "$d" -ge 1 ] && [ "$call" -ge 1 ]; then say "case2 ordinary def+call" "PASS"; else say "case2 ordinary def+call" "FAIL (def=$d call=$call)"; fail=1; fi

# --- Case 3: genuine fn-ptr-RETURNING definition must still be a def
cat > d.c <<'C'
int (*make_handler(int x))(void) { return 0; }
C
"$CS" -bk d.c -f cs3.out >/dev/null 2>&1
d3=$("$CS" -d -f cs3.out -L1 make_handler | wc -l | tr -d ' ')
if [ "$d3" -ge 1 ]; then say "case3 fn-ptr-returning def" "PASS"; else say "case3 fn-ptr-returning def" "FAIL (def=$d3)"; fail=1; fi

[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAILED"
exit $fail
