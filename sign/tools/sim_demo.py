"""Render demo.py frames on the PC (fake PicoGraphics) into a contact sheet PNG, and time each scene.
Fonts are approximated, so check text placement on the real board.
Usage: python sim_demo.py out.png"""
import sys, time, types
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # the shows live one folder up
from PIL import Image, ImageDraw, ImageFont

W, H = 53, 11
mp = types.ModuleType("micropython")
mp.native = lambda f: f
sys.modules["micropython"] = mp

FONT = ImageFont.load_default(size=8)


class FakeGfx:
    def __init__(self):
        self.fb = [[(0, 0, 0)] * W for _ in range(H)]
        self.pen = (0, 0, 0)

    def create_pen(self, r, g, b):
        return (r, g, b)

    def set_pen(self, p):
        self.pen = p

    def set_font(self, f):
        pass

    def clear(self):
        self.fb = [[self.pen] * W for _ in range(H)]

    def pixel(self, x, y):
        if 0 <= x < W and 0 <= y < H:
            self.fb[y][x] = self.pen

    def rectangle(self, x, y, w, h):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.pixel(xx, yy)

    def measure_text(self, s, scale=1):
        return sum(4 if c in "1I!.:' " else 6 for c in s)  # roughly bitmap6

    def text(self, s, x, y, wrap=-1, scale=1):
        img = Image.new("1", (self.measure_text(s) + 8, 12))
        ImageDraw.Draw(img).text((0, -2), s, font=FONT, fill=1)
        for yy in range(min(6, img.height)):
            for xx in range(img.width):
                if img.getpixel((xx, yy)):
                    self.pixel(x + xx, y + yy)


import demo

hosts = [("N1", "up", 128, 1.0, None), ("N2", "warn", 172, 0.998, "HOT"),
         ("N3", "up", 131, 0.992, None), ("HUB", "down", None, 0.95, None)]
g = FakeGfx()
frames, labels = [], []
ms, step = 0, 40
last_scene, scene_start = -1, 0
timing = {}
while len(timing) < 4 or demo._seq["i"] != 0:
    t0 = time.perf_counter()
    demo.frame(g, ms, hosts)
    i = demo._seq["i"]
    if i != last_scene:
        if last_scene >= 0:
            timing[last_scene] = (ms - scene_start) / 1000
        last_scene, scene_start = i, ms
    rel = ms - scene_start
    keep = (400, 1000, 2000, 2600, 3200, 5500, 7000, 9000) if demo.SCENES[i].__name__ in ("scene_donut", "scene_morph") else (2000, 12000, 30000) if demo.SCENES[i].__name__ == "scene_scroller" else (2000, 4000)
    if rel in keep:
        frames.append([row[:] for row in g.fb])
        labels.append("%s +%.1fs" % (demo.SCENES[i].__name__, rel / 1000))
    ms += step
    if ms > 200000:
        break
print("scene lengths (s):", {demo.SCENES[k].__name__: v for k, v in timing.items()})

S = 8
img = Image.new("RGB", (W * S + 140, len(frames) * (H * S + 6)), (25, 25, 25))
d = ImageDraw.Draw(img)
for n, (fb, lab) in enumerate(zip(frames, labels)):
    oy = n * (H * S + 6)
    for y in range(H):
        for x in range(W):
            d.ellipse([x * S + 1, oy + y * S + 1, x * S + S - 2, oy + y * S + S - 2], fill=fb[y][x])
    d.text((W * S + 6, oy + 30), lab, fill=(200, 200, 200))
img.save(sys.argv[1] if len(sys.argv) > 1 else "demo_sheet.png")
print(len(frames), "frames")
