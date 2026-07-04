static int cmp(const void *a, const void *b) { return 0; }
extern void my_sort(void *base, int (*f)(const void *, const void *));
void sort_things(void *arr) { my_sort(arr, cmp); }
void log_fake(void) { const char *s = "cmp(x)"; (void)s; }
