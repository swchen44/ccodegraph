# GT WRQ-012: `robj`/`kvobj` struct definition and refcount-relevant fields

**Question (verbatim):** "Find the definition of the robj struct (or kvobj if robj
is now an alias) and list which fields determine its reference-counting behavior."

**Method:** grepped `src/*.h` for `struct redisObject`, `robj`, `kvobj` typedefs
(confirming the CURRENT checkout's naming — do not trust stale prior knowledge),
located the struct body, then traced every read/write of `refcount` in
`src/object.c`, `src/server.h`, `src/db.c`, `src/module.c`, `src/networking.c`,
`src/server.c`, `src/slowlog.c`, `src/t_stream.c`, `src/cluster_asm.c` to find
which sentinel constants change refcounting semantics.

## Struct name in THIS checkout

The rename has already happened here, but **not as a full split**: both `robj`
and `kvobj` are currently typedefs of the *same* underlying struct.

- `src/object.h:100-112` — struct body:
  ```c
  struct redisObject {
      unsigned type:4;
      unsigned encoding:4;
      unsigned refcount : OBJ_REFCOUNT_BITS;
      unsigned iskvobj : 1;   /* 1 if this struct serves as a kvobj base */
      unsigned metabits :8;   /* Bitmap of metadata (+expiry) attached to this kvobj */
      unsigned lru:LRU_BITS;
      void *ptr;
  };
  ```
- `src/object.h:115` — `typedef struct redisObject robj;` (general-purpose object)
- `src/object.h:118` — `typedef struct redisObject kvobj;` (key-value object —
  same layout, distinguished at runtime by the `iskvobj` flag, not by a
  different C struct). Per the header comment at `src/object.h:24-30`, `kvobj`
  is conceptually a child of `robj` ("a specific use of robj that additionally
  embeds the key"), identified by `iskvobj`, but as of this checkout it is not
  yet a separate C type — both names resolve to `struct redisObject`.

So the correct answer to "is robj now an alias" is: **yes, `robj` is a typedef
alias for `struct redisObject`, and so (currently) is `kvobj` — they are the
same struct**, defined at `src/object.h:100`.

## Full field listing (`struct redisObject`, src/object.h:100-111)

| field | bits/type | purpose |
|---|---|---|
| `type` | `unsigned:4` | object type (OBJ_STRING, OBJ_LIST, ...) |
| `encoding` | `unsigned:4` | in-memory encoding (OBJ_ENCODING_*) |
| `refcount` | `unsigned:OBJ_REFCOUNT_BITS` (23 bits) | **reference count / sentinel** |
| `iskvobj` | `unsigned:1` | 1 if this object also serves as a kvobj base (has embedded key/metadata) |
| `metabits` | `unsigned:8` | bitmap of metadata classes attached (only meaningful when `iskvobj`) |
| `lru` | `unsigned:LRU_BITS` (24 bits) | LRU clock or LFU counter/access-time (not refcount-related) |
| `ptr` | `void *` | pointer to payload (sds/dict/quicklist/...) |

## Field(s)/values that govern reference-counting behavior

1. **`refcount`** (`src/object.h:103`) is the primary field — a 23-bit
   (`OBJ_REFCOUNT_BITS`, `src/object.h:95`) unsigned bitfield incremented by
   `incrRefCount()` and decremented by `decrRefCount()` (`src/object.c:629`,
   `src/object.c:643`). When it hits 0 in `decrRefCount`, the object's storage
   is freed.

2. Two **sentinel values** of `refcount` change the counting behavior entirely
   — they are not "large ref counts", they mean "do not refcount this object
   at all":
   - **`OBJ_SHARED_REFCOUNT`** — `src/object.h:96`:
     `#define OBJ_SHARED_REFCOUNT ((1 << OBJ_REFCOUNT_BITS) - 1)`
     ("Global object never destroyed.") Used for shared integers / shared
     objects created by `makeObjectShared()` (`src/object.c:143-147`, which
     asserts `refcount == 1` before switching it to this sentinel).
     - `incrRefCount` (`src/object.c:633-634`): if refcount is already
       `OBJ_SHARED_REFCOUNT`, do nothing — "this refcount is immutable."
     - `decrRefCount` (`src/object.c:644-645`): if refcount is
       `OBJ_SHARED_REFCOUNT`, return immediately without freeing — "Nothing to
       do: this refcount is immutable."
   - **`OBJ_STATIC_REFCOUNT`** — `src/object.h:97`:
     `#define OBJ_STATIC_REFCOUNT ((1 << OBJ_REFCOUNT_BITS) - 2)`
     ("Object allocated in the stack.") Set by the
     `initStaticStringObject()` macro (`src/server.h:1111-1118`) for
     stack-allocated temporary robjs.
     - `incrRefCount` (`src/object.c:635-636`): if refcount equals
       `OBJ_STATIC_REFCOUNT`, `serverPanic("You tried to retain an object
       allocated in the stack")` — retaining a static object is a bug, not a
       no-op.
     - `decrRefCount` has no special-case for `OBJ_STATIC_REFCOUNT`, so callers
       are expected to skip calling it on such objects (seen at call sites,
       e.g. `src/server.c:489-493`, `src/t_stream.c:6106`, which explicitly
       test `refcount == OBJ_STATIC_REFCOUNT` before deciding whether to
       decode/decrRefCount).
   - **`OBJ_FIRST_SPECIAL_REFCOUNT`** — `src/object.h:98`:
     `#define OBJ_FIRST_SPECIAL_REFCOUNT OBJ_STATIC_REFCOUNT` — the threshold
     used by `incrRefCount` (`o->refcount < OBJ_FIRST_SPECIAL_REFCOUNT - 1`,
     `src/object.c:630`) and by other code (e.g.
     `src/networking.c:1284`: `obj->refcount >= OBJ_FIRST_SPECIAL_REFCOUNT`) to
     detect "this refcount value is one of the special sentinels, not a real
     count" before doing ordinary increment/decrement or copy-on-write logic.

3. **`iskvobj`** is not itself a refcounting field, but it changes *what
   `decrRefCount` does when the count reaches 0*: `src/object.c` (fast-path
   embedded-string free at line ~655 checks `!o->iskvobj`; when `iskvobj` is
   set, `decrRefCount` computes the real allocation pointer via
   `kvobjGetAllocPtr(o)` and additionally frees per-key metadata via
   `keyMetaOnFree()` before releasing memory). So `iskvobj` gates which
   deallocation path fires once refcount hits zero, making it relevant to
   "reference-counting behavior" in the broad sense the question asks about,
   even though it does not gate whether/when decrement happens.

## What is NOT part of the answer

`type`, `encoding`, `metabits`, `lru`, `ptr` play no role in refcount
semantics — `lru` in particular is easy to mis-flag because it sits in the
same bitfield-packed region of the struct as `refcount`, but it is purely an
eviction/LFU-clock field, unrelated to freeing.

## Scoring rubric (0-3)

- **0** — Wrong struct/file, or answer is only about `struct redisObject`
  fields unrelated to refcounting (e.g., lists `type`/`encoding`/`lru` as "the"
  refcount fields), or claims `kvobj` is a distinct/separate struct without
  checking (it is currently the same typedef as `robj` in this checkout).
- **1** — Finds `struct redisObject` (object.h:100) and identifies `refcount`
  as the field, but misses both sentinel constants (`OBJ_SHARED_REFCOUNT`,
  `OBJ_STATIC_REFCOUNT`) entirely.
- **2** — Finds `refcount` and at least one of the two sentinel constants
  (`OBJ_SHARED_REFCOUNT` or `OBJ_STATIC_REFCOUNT`) with correct effect
  (shared = immutable/never freed, or static = never retained/panics), with
  file:line for the struct.
- **3** — Full credit: identifies `struct redisObject` at `src/object.h:100`
  as the current definition (correctly notes `robj`/`kvobj` are both typedef
  aliases of it, per `src/object.h:115,118`), names `refcount` as the primary
  field, and explains **both** sentinel values —
  `OBJ_SHARED_REFCOUNT` (`src/object.h:96`, incr is a no-op, decr is a no-op —
  "never destroyed") and `OBJ_STATIC_REFCOUNT` (`src/object.h:97`, incr panics
  — "allocated in the stack", set via `initStaticStringObject`,
  `src/server.h:1111`) — with correct locations. Bonus (not required for 3,
  but shows depth): mentions `OBJ_FIRST_SPECIAL_REFCOUNT` as the threshold
  constant used to detect either sentinel, and/or notes `iskvobj` changes the
  free path taken once refcount reaches 0.
