from pathlib import Path
import textwrap

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Pillow is required to render this infographic.") from exc


W = 1200
OUT = Path("lsp-trilogy.png")

NAVY = "#1a2332"
PAGE = "#f7f9fc"
WHITE = "#ffffff"
SUBTLE = "#8fa3bf"
TEXT = "#444444"
MUTED = "#556070"
BORDER = "#dde3ec"
PILL_BORDER = "#b9c4d4"
BOX_BORDER = "#3a4a63"
TEAL = "#0e9594"
AMBER = "#e8a13c"
CORAL = "#d95d55"


def font(size, bold=False):
    candidates = [
        ("/System/Library/Fonts/Helvetica.ttc", 1 if bold else 0),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf", 0),
        ("/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
    ]
    for path, index in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=index)
            except TypeError:
                return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


F_TITLE = font(54, True)
F_SUBTITLE = font(26)
F_BADGE = font(23, True)
F_CARD_HEAD = font(23, True)
F_BIG = font(64, True)
F_BIG_UNIT = font(30, True)
F_BULLET = font(20)
F_WHY_HEAD = font(34, True)
F_WHY = font(24)
F_FOOT = font(24)
F_SMALL = font(20)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def center_text(draw, xywh, text, fnt, fill):
    x, y, w, h = xywh
    tw, th = text_size(draw, text, fnt)
    draw.text((x + (w - tw) / 2, y + (h - th) / 2 - 2), text, font=fnt, fill=fill)


def fitted_font(draw, text, start_size, max_width, bold=True, min_size=24):
    size = start_size
    while size > min_size:
        fnt = font(size, bold)
        if text_size(draw, text, fnt)[0] <= max_width:
            return fnt
        size -= 1
    return font(min_size, bold)


def wrapped_lines(draw, text, fnt, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if text_size(draw, trial, fnt)[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_bullet(draw, x, y, text, max_width):
    draw.text((x, y), "•", font=F_BULLET, fill=TEXT)
    lines = wrapped_lines(draw, text, F_BULLET, max_width - 30)
    line_y = y
    for line in lines:
        draw.text((x + 26, line_y), line, font=F_BULLET, fill=TEXT)
        line_y += 27
    return line_y + 12


def bullet_block_end(draw, y, bullets, max_width):
    by = y
    for bullet in bullets:
        lines = wrapped_lines(draw, bullet, F_BULLET, max_width - 30)
        by += 27 * len(lines) + 12
    return by


def draw_big_stat(draw, x, y, w, color, number):
    max_width = w - 48
    if isinstance(number, tuple):
        value, unit = number
        value_font = fitted_font(draw, value, 64, max_width, True)
        unit_font = fitted_font(draw, unit, 30, max_width, True)
        center_text(draw, (x + 24, y + 92, max_width, 58), value, value_font, color)
        center_text(draw, (x + 24, y + 150, max_width, 34), unit, unit_font, color)
        return

    stat_font = fitted_font(draw, number, 64, max_width, True)
    center_text(draw, (x + 24, y + 104, max_width, 80), number, stat_font, color)


def draw_card(draw, x, y, w, h, color, label, number, bullets):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=WHITE, outline=BORDER, width=1)
    draw.rounded_rectangle((x, y, x + w, y + 64), radius=16, fill=color)
    draw.rectangle((x, y + 32, x + w, y + 64), fill=color)
    center_text(draw, (x + 18, y + 5, w - 36, 56), label, F_CARD_HEAD, WHITE)
    draw_big_stat(draw, x, y, w, color, number)
    by = y + 238
    for bullet in bullets:
        by = draw_bullet(draw, x + 34, by, bullet, w - 68)


def draw_terminal(draw, cx, y, color):
    x = cx - 62
    draw.rounded_rectangle((x, y, x + 124, y + 84), radius=10, outline=color, width=5)
    draw.line((x, y + 22, x + 124, y + 22), fill=color, width=4)
    draw.line((x + 18, y + 50, x + 34, y + 60, x + 18, y + 70), fill=color, width=5, joint="curve")
    draw.line((x + 46, y + 70, x + 82, y + 70), fill=color, width=5)


def draw_shield(draw, cx, y, color):
    pts = [(cx, y), (cx + 55, y + 18), (cx + 45, y + 72), (cx, y + 102), (cx - 45, y + 72), (cx - 55, y + 18)]
    draw.line(pts + [pts[0]], fill=color, width=5, joint="curve")
    draw.line((cx - 25, y + 52, cx - 7, y + 70, cx + 30, y + 35), fill=color, width=8, joint="curve")


def main():
    card_y, card_w, gap = 250, 340, 30
    cards = [
        (TEAL, "ROUND 1 · Navigation", "60 = 60", [
            "36% of runs never called LSP",
            "incomingCalls: 4 uses in 66 runs",
            "teaching skill: only +1 point",
        ]),
        (AMBER, "ROUND 2 · Editing", "24/24 ×4", [
            "dead tie, compiler-judged",
            "diagnostics = make",
            "agents run make ~3x anyway",
        ]),
        (CORAL, "ROUND 3 · Slow builds", ("−83%", "checks"), [
            "make priced at ~60s each",
            "agents simply skip verification",
            "still all-PASS — trust was right",
        ]),
    ]
    scratch = Image.new("RGB", (W, 1), WHITE)
    scratch_draw = ImageDraw.Draw(scratch)
    card_h = max(bullet_block_end(scratch_draw, 238, card[-1], card_w - 68) for card in cards) + 40
    why_y = card_y + card_h + 40
    why_h = 290
    footer_y = why_y + why_h
    H = footer_y + 270

    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 210), fill=NAVY)
    draw.text((60, 62), "LSP for AI Coding Agents", font=F_TITLE, fill=WHITE)
    draw.text((62, 132), "3 controlled benchmarks · 390 runs · it never beat grep + make", font=F_SUBTITLE, fill=SUBTLE)
    badge = "0 WINS / 3 ROUNDS"
    bw, bh = text_size(draw, badge, F_BADGE)
    bx, by = W - 60 - bw - 44, 58
    draw.rounded_rectangle((bx, by, bx + bw + 44, by + 50), radius=25, fill=CORAL)
    center_text(draw, (bx, by, bw + 44, 50), badge, F_BADGE, WHITE)

    draw.rectangle((0, 210, W, why_y), fill=PAGE)
    xs = [60, 60 + card_w + gap, 60 + (card_w + gap) * 2]
    for x, card in zip(xs, cards):
        draw_card(draw, x, card_y, card_w, card_h, *card)

    draw.rectangle((0, why_y, W, footer_y), fill=NAVY)
    center_text(draw, (0, why_y + 40, W, 46), "WHY LSP NEVER PAYS OFF HERE", F_WHY_HEAD, WHITE)
    box_w, box_h, box_y = 500, 142, why_y + 114
    left_x, right_x = 80, 620
    for x in (left_x, right_x):
        draw.rounded_rectangle((x, box_y, x + box_w, box_y + box_h), radius=16, outline=BOX_BORDER, width=2)
    draw_terminal(draw, left_x + 88, box_y + 30, TEAL)
    draw_shield(draw, right_x + 88, box_y + 20, AMBER)
    draw.text((left_x + 180, box_y + 38), "grep + make is already", font=F_WHY, fill=WHITE)
    draw.text((left_x + 180, box_y + 76), "a complete workflow", font=F_WHY, fill=WHITE)
    draw.text((right_x + 180, box_y + 34), "model edits are already correct —", font=F_WHY, fill=WHITE)
    draw.text((right_x + 180, box_y + 72), "verification itself is optional", font=F_WHY, fill=WHITE)

    draw.rectangle((0, footer_y, W, H), fill=PAGE)
    pills = ["N=3 medians", "compiler as judge", "diagnostics isolation arm", "full repro package"]
    widths = [text_size(draw, p, F_FOOT)[0] + 42 for p in pills]
    total = sum(widths) + 22 * (len(pills) - 1)
    px = (W - total) / 2
    py = footer_y + 60
    for label, pw in zip(pills, widths):
        draw.rounded_rectangle((px, py, px + pw, py + 48), radius=24, outline=PILL_BORDER, width=2)
        center_text(draw, (px, py, pw, 48), label, F_FOOT, MUTED)
        px += pw + 22
    footer = "github.com/swchen44/ccodegraph  ·  C repos: wpa_supplicant / redis  ·  claude sonnet  ·  2026"
    center_text(draw, (0, footer_y + 163, W, 34), footer, F_SMALL, "#737b87")

    img.save(OUT, "PNG", compress_level=1)
    size = OUT.stat().st_size
    print(f"{OUT} {size} bytes")
    if size <= 50 * 1024:
        raise SystemExit(f"{OUT} is too small: {size} bytes")


if __name__ == "__main__":
    main()
