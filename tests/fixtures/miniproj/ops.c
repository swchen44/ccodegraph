struct ops { int (*run)(void); };
static int impl_run(void) { return 0; }
static struct ops OPS = { .run = impl_run };
int dispatch_op(struct ops *o) { return o->run(); }
int extra_handler(void) { return 7; }
