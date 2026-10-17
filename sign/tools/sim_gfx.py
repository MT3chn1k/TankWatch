"""Fake PicoGraphics for previewing Unicorn effects on the PC (fonts approximated)."""
import sys, types
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




def sheet(frames, labels, path, S=8):
    img = Image.new("RGB", (W * S + 150, len(frames) * (H * S + 6)), (25, 25, 25))
    d = ImageDraw.Draw(img)
    for n, (fb, lab) in enumerate(zip(frames, labels)):
        oy = n * (H * S + 6)
        for y in range(H):
            for x in range(W):
                d.ellipse([x * S + 1, oy + y * S + 1, x * S + S - 2, oy + y * S + S - 2], fill=fb[y][x])
        d.text((W * S + 6, oy + 30), lab, fill=(200, 200, 200))
    img.save(path)
