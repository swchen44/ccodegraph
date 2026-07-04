#include "util.h"

int counter = 0;

int add(int a, int b) { return a + b; }

static int helper(void) { return 1; }

int use_helper(void) { return helper(); }

int get_counter(void) { return counter; }
