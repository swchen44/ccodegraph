void register_handler(RxResult (*handler)(void), void *data);

/* Minimized from wpa_supplicant src/radius/radius_client.h:239
   (the "RadiusRxResult (*handler)" function-pointer parameter).
   The identifier before "(*...)(" is the return TYPE, not a
   function definition. See sf bug #306; provenance in README.md. */
