"""ページの一番上に出す画像（ファーストビュー）を作る。SNSで共有されたときの画像にも使う。

イベント名と日付、その日の空き具合の数字を大きく見せる。写真は使わず、会場の形を簡単な図形で描く。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
NAVY = (18, 80, 122)
INK = (27, 38, 51)
MUTED = (91, 104, 117)
YELLOW = (245, 197, 24)
SOFT = (232, 241, 247)
LINE = (214, 222, 229)

FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
]


def font(size):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size, index=0)
    raise RuntimeError("日本語のフォントが見つかりません")


def wrap(draw, text, f, width, max_lines):
    """文字幅に合わせて行を分ける。入りきらなければ最後を「…」にする。"""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=f) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def venue_mark(draw, x, y, s):
    """会議棟の逆三角形を4つ並べた形を簡単に描く。"""
    w = s / 4
    for i in range(4):
        cx = x + w * i
        draw.polygon([(cx, y), (cx + w - 6, y), (cx + w / 2 - 3, y + s * 0.42)], fill=SOFT, outline=NAVY, width=4)
    draw.rectangle([x + s * 0.18, y + s * 0.42, x + s * 0.78, y + s * 0.72], fill=SOFT, outline=NAVY, width=4)
    draw.line([x - 10, y + s * 0.72, x + s + 4, y + s * 0.72], fill=NAVY, width=5)


def make_hero(out_path, title, sub, tiles, lead="の会場に近いホテル", site="ちか宿", tagline="会場に近い宿さがし"):
    """title: イベント名など, lead: 見出しの続き, sub: 日付や会場, tiles: [(ラベル, 数字, 単位)] を3つまで。"""
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    # 上の帯
    d.rectangle([0, 0, W, 86], fill=NAVY)
    d.ellipse([48, 22, 90, 64], outline=(255, 255, 255), width=5)
    d.ellipse([62, 36, 76, 50], fill=YELLOW)
    d.text((108, 18), site, font=font(40), fill=(255, 255, 255))
    d.text((108 + d.textlength(site, font=font(40)) + 18, 34), tagline, font=font(24), fill=(200, 220, 235))

    # 見出し
    ft = font(60 if len(title) > 14 else 68)
    lines = wrap(d, title, ft, 830, 2)
    y = 112
    for line in lines:
        d.text((56, y), line, font=ft, fill=INK)
        y += ft.size + 14
    if lead:
        d.text((58, y), lead, font=font(40), fill=NAVY)
        y += 56
    d.text((58, y + 4), sub, font=font(30), fill=MUTED)

    # 会場の形
    venue_mark(d, 930, 140, 210)

    # 下の数字
    n = max(1, len(tiles))
    gap = 20
    tw = (W - 56 * 2 - gap * (n - 1)) / n
    ty = 432
    for i, (label, value, unit) in enumerate(tiles):
        x0 = 56 + i * (tw + gap)
        d.rounded_rectangle([x0, ty, x0 + tw, ty + 170], radius=18, fill=(255, 255, 255), outline=NAVY, width=4)
        d.text((x0 + tw / 2, ty + 34), label, font=font(26), fill=MUTED, anchor="mm")
        fv, fu = font(76), font(32)
        vw = d.textlength(value, font=fv)
        uw = d.textlength(unit, font=fu)
        sx = x0 + (tw - vw - uw - 6) / 2
        d.text((sx, ty + 132), value, font=fv, fill=NAVY, anchor="ls")
        d.text((sx + vw + 6, ty + 130), unit, font=fu, fill=INK, anchor="ls")
        d.rectangle([x0 + tw / 2 - 40, ty + 146, x0 + tw / 2 + 40, ty + 152], fill=YELLOW)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=86, optimize=True, progressive=True)
    return out_path
