# -*- coding: utf-8 -*-
"""ヒーローのロゴマーク(白線画の双耳峰+雪)から PWA アイコン4サイズを生成する。

出力先: icons/ (apple-touch-icon.png / icon-192.png / icon-512.png / favicon-32.png)

index.html の .logomark SVG (viewBox 0 0 76 52) を忠実に再現:
  外形:   M4 48 L28 8 L40 27 L50 14 L72 48 Z  (stroke #fff / stroke-width 3.5 / round-join)
  雪(左): M21.5 19 L28 8 L34.5 19 L31.2 15.6 L28 19.6 L24.8 15.6 Z (fill)
  雪(右): M45.8 20.5 L50 14 L54.2 20.5 L52 18.2 L50 20.8 L48 18.2 Z (fill)
背景はヒーローと同じネイビー系だが、v2.00 では対角線形グラデ(左上=明るめ #4A6DA5 →
右下=深い #141D38)にしてレンジを広げた。基本色相(ネイビー)は同じまま、グラデを効かせている。
iOS が自動で角丸にするためフルブリード正方形・不透過で出力する。

ロゴマークを変えたら index.html の上記パスを直してここに反映 → `python scripts/gen_icons.py`。
依存: Pillow (pip install -r requirements-dev.txt)
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "icons"

OUTLINE = [(4, 48), (28, 8), (40, 27), (50, 14), (72, 48)]
SNOW_L = [(21.5, 19), (28, 8), (34.5, 19), (31.2, 15.6), (28, 19.6), (24.8, 15.6)]
SNOW_R = [(45.8, 20.5), (50, 14), (54.2, 20.5), (52, 18.2), (50, 20.8), (48, 18.2)]
VB_W, VB_H = 76, 52

GRAD_TL = (0x4A, 0x6D, 0xA5)  # 左上: 現状の GRAD_TOP より明るく彩度も上げたネイビー
GRAD_BR = (0x14, 0x1D, 0x38)  # 右下: --night(#1e2d4a) より深いネイビー


def make_icon(size, mark_ratio, stroke_svg, out_name):
    SS = 4  # スーパーサンプリング倍率(アンチエイリアス用)
    S = size * SS
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)

    # 対角線形グラデーション背景。x+y の等高線に沿って色を補間する
    # (左上→右下の対角と垂直な線が同色になる)。t=0が左上、t=1が右下。
    N = 2 * (S - 1)
    for k in range(N + 1):
        t = k / N
        c = tuple(round(a + (b - a) * t) for a, b in zip(GRAD_TL, GRAD_BR))
        x0 = max(0, k - (S - 1)); y0 = k - x0
        x1 = min(S - 1, k);       y1 = k - x1
        d.line([(x0, y0), (x1, y1)], fill=c)

    # マークの配置: 幅 mark_ratio、光学的中央(わずかに上)に置く
    scale = S * mark_ratio / VB_W
    mw, mh = VB_W * scale, VB_H * scale
    ox, oy = (S - mw) / 2, (S - mh) / 2 - S * 0.01

    def pt(p):
        return (ox + p[0] * scale, oy + p[1] * scale)

    w = max(1, round(stroke_svg * scale))
    pts = [pt(p) for p in OUTLINE]
    # 閉じた輪郭を round-join で描く(先頭2点を繰り返して閉じ目の角も丸める)
    d.line(pts + [pts[0], pts[1]], fill="#ffffff", width=w, joint="curve")
    # 端点の丸め(round-cap 相当)
    for p in pts:
        r = w / 2
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill="#ffffff")
    d.polygon([pt(p) for p in SNOW_L], fill="#ffffff")
    d.polygon([pt(p) for p in SNOW_R], fill="#ffffff")

    img = img.resize((size, size), Image.LANCZOS)
    img.save(OUT / out_name)
    print(f"{out_name}: {size}x{size} mark={int(mark_ratio * 100)}% stroke={stroke_svg}")


def main():
    OUT.mkdir(exist_ok=True)
    # iOS/Android: マークは幅62%、線は SVG と同じ 3.5
    make_icon(180, 0.62, 3.5, "apple-touch-icon.png")
    make_icon(192, 0.62, 3.5, "icon-192.png")
    make_icon(512, 0.62, 3.5, "icon-512.png")
    # favicon: 小さいので線を太めにして視認性を確保
    make_icon(32, 0.80, 6.0, "favicon-32.png")


if __name__ == "__main__":
    main()
