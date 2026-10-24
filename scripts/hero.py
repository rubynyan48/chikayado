"""ページの一番上に出す画像（ファーストビュー）を作る。SNSで共有されたときの画像にも使う。

イベント名と日付、その日の空き具合の数字を大きく見せる。背景は assets/photos の会場写真。
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


def cover(photo):
    """写真を画像の大きさいっぱいに広げて、はみ出す分を切り落とす。"""
    im = Image.open(photo).convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def shade(img):
    """文字が読めるように、左と下を紺色で暗くする。右側は写真が見えるように薄くする。"""
    mask = Image.new("L", (W, H))
    px = mask.load()
    for x in range(W):
        a = 200 if x < 380 else max(30, int(200 - (x - 380) * 0.3))
        for y in range(H):
            b = a if y < 410 else min(200, a + int((y - 410) * 0.6))
            px[x, y] = b
    layer = Image.new("RGB", (W, H), (10, 40, 64))
    return Image.composite(layer, img, mask)


def make_hero(out_path, title, sub, tiles, lead="の会場に近いホテル", site="ちか宿", tagline="会場に近い宿さがし", photo=None):
    """title: イベント名など, lead: 見出しの続き, sub: 日付や会場, tiles: [(ラベル, 数字, 単位)] を3つまで。"""
    img = shade(cover(photo)) if photo and Path(photo).exists() else Image.new("RGB", (W, H), (10, 40, 64))
    d = ImageDraw.Draw(img)
    # 上の帯
    d.rectangle([0, 0, W, 86], fill=NAVY)
    icon = Path(__file__).resolve().parent.parent / "assets" / "photos" / "ちか宿のアイコン.png"
    if icon.exists():
        d.rounded_rectangle([44, 14, 102, 72], radius=12, fill=(255, 255, 255))
        ic = Image.open(icon).convert("RGBA").resize((50, 50), Image.LANCZOS)
        img.paste(ic, (48, 18), ic)
    d.text((108, 18), site, font=font(40), fill=(255, 255, 255))
    d.text((108 + d.textlength(site, font=font(40)) + 18, 34), tagline, font=font(24), fill=(200, 220, 235))

    # 見出し
    ft = font(60 if len(title) > 14 else 68)
    lines = wrap(d, title, ft, 760, 2)
    y = 112
    for line in lines:
        d.text((56, y), line, font=ft, fill=(255, 255, 255))
        y += ft.size + 14
    if lead:
        d.text((58, y), lead, font=font(40), fill=YELLOW)
        y += 56
    d.text((58, y + 4), sub, font=font(30), fill=(220, 232, 242))

    # 下の数字
    n = max(1, len(tiles))
    gap = 20
    tw = (W - 56 * 2 - gap * (n - 1)) / n
    ty = 432
    for i, (label, value, unit) in enumerate(tiles):
        x0 = 56 + i * (tw + gap)
        d.rounded_rectangle([x0, ty, x0 + tw, ty + 170], radius=18, fill=(255, 255, 255))
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
