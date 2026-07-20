/* cscope sf bug #306 — reproducer, file 2 of 2.
 *
 * Any second file containing any call.  Before the fix, the call
 * below is double-attributed: once to dispatch() (correct) and once
 * to the phantom "RxResult" definition that leaked out of a.h.
 *
 *   $ cscope -bk a.h b.c -f cs.out
 *   $ cscope -d -f cs.out -L3 probe_call
 *   b.c RxResult  3 probe_call();   <- stock 15.9: phantom caller
 *   b.c dispatch  3 probe_call();   <- correct
 *   (patched: only the dispatch line remains) */
static int dispatch(void)
{
	probe_call();
	return 0;
}
