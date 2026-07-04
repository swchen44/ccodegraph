#include "sub1/config.h"
int app_init(void);
int do_start(void) { return app_init(); }
int use_cfg(void) { return cfg_get(); }
