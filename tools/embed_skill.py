#!/usr/bin/env python3
"""把 skills/ccodegraph/SKILL.md 以「純文字」內嵌進 ccodegraph.py(triple-quoted
字串,可直接在 ccodegraph.py 裡閱讀與修改——使用者要求,取代舊 base64 分塊)。
編輯 SKILL.md 後跑這支;一致性由 unit test 強制
(tests/unit/test_core.py::TestEmbeddedSkill)。

安全前提(違反時本腳本直接失敗,不產生壞檔):內容不得含 ''' 或反斜線或 CR,
且必須以換行結尾——目前的 SKILL.md 皆滿足;未來若加入這些字元,先改這裡的
嵌入策略再說,不要靜默轉義。
副作用:SKILL.md 有 6 行 >100 字元(frontmatter description 與 cheatsheet),
字串字面值內無法放 noqa,故 pyproject.toml 對 ccodegraph.py 單檔豁免 E501。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "ccodegraph", "SKILL.md")
PY = os.path.join(ROOT, "ccodegraph.py")
BEGIN = "# --- EMBEDDED_SKILL_BEGIN(由 tools/embed_skill.py 生成,勿手改)---"
END = "# --- EMBEDDED_SKILL_END ---"

with open(SKILL, encoding="utf-8") as fh:
    text = fh.read()
assert "'''" not in text, "SKILL.md 含 ''',會撞字串分隔符——先改嵌入策略"
assert "\\" not in text, "SKILL.md 含反斜線,純文字嵌入會被跳脫——先改嵌入策略"
assert "\r" not in text, "SKILL.md 含 CR"
assert text.endswith("\n"), "SKILL.md 必須以換行結尾"

block = (f"{BEGIN}\n"
         f"SKILL_MD = '''\\\n{text}'''\n"
         f"{END}")

with open(PY, encoding="utf-8") as fh:
    src = fh.read()
if BEGIN in src:
    head, _, rest = src.partition(BEGIN)
    _, _, tail = rest.partition(END)
    src = head + block + tail
else:
    anchor = 'DB_NAME = os.path.join(PRODUCTS_DIR, "graph.db")'
    assert anchor in src, "anchor missing"
    src = src.replace(anchor, anchor + "\n\n" + block, 1)
with open(PY, "w", encoding="utf-8") as fh:
    fh.write(src)
print(f"embedded {len(text.encode())} bytes of SKILL.md into ccodegraph.py (plain text)")
