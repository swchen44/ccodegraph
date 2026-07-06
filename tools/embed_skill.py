#!/usr/bin/env python3
"""把 skills/ccodegraph/SKILL.md 內嵌進 ccodegraph.py(base64 分塊,避開跳脫
與行長問題)。編輯 SKILL.md 後跑這支;一致性由 unit test 強制
(tests/unit/test_core.py::TestEmbeddedSkill)。"""
import base64
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "ccodegraph", "SKILL.md")
PY = os.path.join(ROOT, "ccodegraph.py")
BEGIN = "# --- EMBEDDED_SKILL_BEGIN(由 tools/embed_skill.py 生成,勿手改)---"
END = "# --- EMBEDDED_SKILL_END ---"

with open(SKILL, "rb") as fh:
    raw = fh.read()
b64 = base64.b64encode(raw).decode()
chunks = "\n".join(f'    "{b64[i:i + 76]}"' for i in range(0, len(b64), 76))
block = (f"{BEGIN}\n_SKILL_B64 = (\n{chunks}\n)\n"
         f"SKILL_MD = base64.b64decode(_SKILL_B64).decode()\n{END}")

with open(PY) as fh:
    src = fh.read()
if BEGIN in src:
    head, _, rest = src.partition(BEGIN)
    _, _, tail = rest.partition(END)
    src = head + block + tail
else:
    anchor = 'DB_NAME = os.path.join(PRODUCTS_DIR, "graph.db")'
    assert anchor in src, "anchor missing"
    src = src.replace(anchor, anchor + "\n\n" + block, 1)
with open(PY, "w") as fh:
    fh.write(src)
print(f"embedded {len(raw)} bytes of SKILL.md into ccodegraph.py")
