static int dispatch(void)
{
	probe_call();
	return 0;
}

/* Second file: any call. Before the fix, probe_call() is double-
   attributed to the phantom "RxResult" definition leaked from a.h. */
