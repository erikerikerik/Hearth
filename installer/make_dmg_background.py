#!/usr/bin/env python3
"""Generate the DMG window background (660x400 pt) at 1x and 2x. Run once; outputs are committed."""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "assets")
out.mkdir(parents=True, exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def render(scale):
    W, H = 660 * scale, 400 * scale
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            d = min(1.0, math.hypot(x - W / 2, y - H * 0.45) / (W * 0.62))
            px[x, y] = (int(44 - 26 * d), int(29 - 17 * d), int(18 - 10 * d))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    # brass arrow between the two icon slots (icons sit at x=165 and x=495, y=190)
    y0 = 190 * scale
    g.line([(250 * scale, y0), (400 * scale, y0)], fill=(214, 168, 92, 255), width=5 * scale)
    g.polygon([(414 * scale, y0), (388 * scale, y0 - 15 * scale), (388 * scale, y0 + 15 * scale)], fill=(214, 168, 92, 255))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(7 * scale)))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)
    big, small = ImageFont.truetype(FONT, 21 * scale), ImageFont.truetype(FONT, 13 * scale)
    for text, font, y, color in (
        ("Drag Hearth into Applications", big, 52, (232, 211, 160, 255)),
        ("Then open it from Applications. It will ask you to set a password.", small, 338, (190, 160, 110, 255)),
    ):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y * scale), text, font=font, fill=color)
    return img.convert("RGB")


render(1).save(out / "dmg-background.png")
render(2).save(out / "dmg-background@2x.png")
print("wrote", out)
