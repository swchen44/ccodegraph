int rarely(void) { return 1; }
int gated(void) {
#ifdef FEATURE_X
    return rarely();
#endif
    return 0;
}
