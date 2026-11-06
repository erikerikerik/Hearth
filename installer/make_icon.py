#!/usr/bin/env python3
"""Generate the Hearth app icon (original filament-ring orb) as AppIcon.icns + preview PNG.

Run once on any machine with Pillow; the .icns is committed so the Mac build needs no Pillow.
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

N = 1024
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "assets")
out.mkdir(parents=True, exist_ok=True)
rnd = random.Random(7)

# Warm dark rounded-square base (macOS-style icon shape, ~22% radius)
base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((40, 40, N - 40, N - 40), radius=210, fill=255)
bg = Image.new("RGBA", (N, N))
px = bg.load()
for y in range(N):
    for x in range(N):
        d = math.hypot(x - N / 2, y - N * 0.44) / (N * 0.7)
        t = min(1, d)
        px[x, y] = (int(38 - 22 * t), int(24 - 14 * t), int(15 - 8 * t), 255)
base.paste(bg, (0, 0), mask)

# Filament ring: many thin wobbling arcs from amber to pale gold
ring = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(ring)
cx = cy = N / 2
for i in range(46):
    r = 262 + rnd.uniform(-16, 16)
    wob = rnd.uniform(6, 22)
    ph = rnd.uniform(0, 6.28)
    k = rnd.choice([2, 3, 4])
    t = rnd.random()
    color = (int(205 + 50 * t), int(150 + 80 * t), int(70 + 90 * t * t), int(120 + 110 * rnd.random()))
    pts = []
    a0 = rnd.uniform(0, 6.28)
    span = rnd.uniform(2.2, 6.28)
    for j in range(121):
        a = a0 + span * j / 120
        rr = r + wob * math.sin(k * a + ph)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.line(pts, fill=color, width=rnd.choice([2, 3, 3, 4]), joint="curve")

glow = ring.filter(ImageFilter.GaussianBlur(26))
glow2 = ring.filter(ImageFilter.GaussianBlur(9))
composed = Image.alpha_composite(base, glow)
composed = Image.alpha_composite(composed, glow2)
composed = Image.alpha_composite(composed, ring)

# soft inner light in the well
well = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ImageDraw.Draw(well).ellipse((cx - 150, cy - 150, cx + 150, cy + 150), fill=(255, 190, 110, 38))
composed = Image.alpha_composite(composed, well.filter(ImageFilter.GaussianBlur(70)))

# keep everything inside the rounded shape
alpha = ImageChops.multiply(composed.getchannel("A"), mask)
composed.putalpha(alpha)
composed.save(out / "AppIcon-1024.png")
composed.save(out / "AppIcon.icns", format="ICNS", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
print("wrote", out / "AppIcon.icns")
