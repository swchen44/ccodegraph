/* cscope sf bug #306 — reproducer, file 1 of 2.
 *
 * Minimized from wpa_supplicant src/radius/radius_client.h:239, the
 * "RadiusRxResult (*handler)(...)" function-pointer PARAMETER of
 * radius_client_register().  Provenance chain (see README.md):
 *   620-file wpa tree  --file-set ddmin-->  {radius_das.c, radius_client.h}
 *   --line ddmin + ablation-->  the single fn-ptr declaration below.
 *
 * The identifier before "(*...)(" (here RxResult) is the return TYPE,
 * NOT a function being defined.  Stock cscope 15.9 records it as an
 * unclosed function definition whose scope leaks into other files. */
void register_handler(RxResult (*handler)(void), void *data);
