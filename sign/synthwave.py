"""Synthwave sunset drive for the Galactic Unicorn, in the EGA palette (side view).

A red convertible cruises right toward a striped sunset. Palm trees whip past in front; behind them
the monitored items drift by as landmarks:
  healthy Pi     clean green peak            warning Pi   yellow volcano puffing smoke
  down Pi        collapsed red rubble        unknown      grey peak
  the tank       a lake with a jumping fish
Each landmark lights up as it passes in front of the sun, and its numbers show on the left:
"N1 100%" then "N1 128F"; the lake cycles "WATER 77.1F", "AIR 71.8F", "HUM 62%".

main.py calls frame(gfx, ms, info) once per display update; info is
{"hosts": [(label, status, temp_f, uptime, why), ...], "tank": (air_f, humidity, water_f)} (each None when missing or stale).
"""
import math
import micropython
from demo import FONT3

W, H = 53, 11
HZ = 7            # mountain bases sit on this row; the road is rows 8-10
SUN_X, SUN_R = 44, 7
SPACING = 30      # px between landmarks
SCENERY_PXS = 6   # landmarks drift 6 px/s
PALM_PXS = 40     # palms whip past
FOCUS_X = 42      # landmarks light up as they pass in front of the sun; their readout shows on the left

EGA = {"black": (0, 0, 0), "blue": (0, 0, 170), "magenta": (170, 0, 170), "lmagenta": (255, 85, 255),
       "cyan": (0, 170, 170), "lcyan": (85, 255, 255), "yellow": (255, 255, 85), "lred": (255, 85, 85),
       "red": (170, 0, 0), "brown": (170, 85, 0), "green": (0, 170, 0), "lgreen": (85, 255, 85),
       "dgray": (85, 85, 85), "lgray": (170, 170, 170), "white": (255, 255, 255), "lblue": (85, 85, 255)}
STATUS = {"up": "lgreen", "warn": "yellow", "down": "lred", None: "lgray"}
DIM = {"up": "green", "warn": "brown", "down": "red", None: "dgray"}
_gfx = None
P = {}


def init(gfx):
    global _gfx
    if _gfx is gfx:
        return
    _gfx = gfx
    for k, rgb in EGA.items():
        P[k] = gfx.create_pen(*rgb)


def tiny(s, x, y, pen):
    g = _gfx
    for pp, dx in ((P["black"], 1), (pen, 0)):
        g.set_pen(pp)
        xx = x
        for ch in s:
            bits = FONT3.get(ch)
            if bits:
                for k in range(15):
                    if bits[k] == "1":
                        g.pixel(xx + k % 3 + dx, y + k // 3 + dx)
            xx += 4


# ---------------------------------------------------------------- backdrop
SUN_ROWS = ("yellow", "yellow", "yellow", "lred", "lred", "lmagenta", "lmagenta")


@micropython.native
def sky_and_sun(t):
    g = _gfx
    g.set_pen(P["blue"])
    g.rectangle(0, 0, 53, 1)
    slide = (t // 300) % 2
    for y in range(HZ):
        dy = HZ - y - 0.5
        half = int(math.sqrt(max(0.0, SUN_R * SUN_R - dy * dy)) + 0.5)
        if half <= 0 or (y >= 3 and (y + slide) % 2 == 0):
            continue  # the classic slices through the lower half
        g.set_pen(P[SUN_ROWS[y]])
        g.rectangle(SUN_X - half, y, half * 2, 1)


@micropython.native
def road(t):
    g = _gfx
    g.set_pen(P["magenta"])
    g.rectangle(0, HZ + 1, 53, 1)           # road edge
    g.set_pen(P["magenta"])
    g.rectangle(0, 10, 53, 1)               # far kerb
    off = (t * 30 // 1000) % 8              # lane dashes rush left
    g.set_pen(P["lmagenta"])
    for x in range(-off, 53, 8):
        g.rectangle(x, 9, 3, 1)


# ---------------------------------------------------------------- landmarks
def _outline_triangle(cx, h, edge, fill):
    """Peak at (cx, HZ - h), base on HZ; black fill hides the sun behind it."""
    g = _gfx
    for r in range(h + 1):
        y = HZ - h + r
        half = r * 3 // 2
        g.set_pen(fill)
        g.rectangle(cx - half, y, half * 2 + 1, 1)
        g.set_pen(edge)
        g.pixel(cx - half, y)
        g.pixel(cx + half, y)
    g.pixel(cx, HZ - h)


def draw_landmark(item, cx, t, lit):
    g = _gfx
    kind = item[0]
    if kind == "tank":
        pen = P["lcyan"] if lit else P["cyan"]
        g.set_pen(pen)
        for x in range(cx - 7, cx + 8):  # lake surface with a little swell
            g.pixel(x, HZ - ((x + t // 200) % 4 == 0))
        jump = (t // 90) % 24  # a fish leaps out now and then
        if jump < 8:
            g.set_pen(P["lred"])
            g.pixel(cx - 3 + jump, HZ - 1 - (2 if 2 <= jump <= 5 else 1))
        return
    status = item[1][1]
    edge = P[STATUS[status]] if lit else P[DIM[status]]
    if status == "down":  # collapsed heap, blinking when lit
        if lit and (t // 300) & 1:
            edge = P["red"]
        g.set_pen(edge)
        for dx, h in ((-5, 1), (-4, 1), (-3, 2), (-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1), (3, 2), (4, 1), (5, 1)):
            g.rectangle(cx + dx, HZ - h + 1, 1, h)
        return
    _outline_triangle(cx, 6, edge, P["black"])
    if status == "warn":  # volcano: flattened crater and smoke
        g.set_pen(P["black"])
        g.pixel(cx, HZ - 6)
        for k in range(3):
            phase = (t // 160 + k * 3) % 9
            if phase < 6:
                g.set_pen(P["lgray"] if phase < 3 else P["dgray"])
                g.pixel(cx + (phase // 2) - k + 1, HZ - 7 - phase // 2)


def readout(item, t):
    """Two alternating short lines for the landmark in focus."""
    second = (t // 1500) & 1
    if item[0] == "tank":
        # the lake is in focus for about 3 s, so cycle its three numbers once a second
        air_f, hum, water_f = item[1]
        phase = (t // 1000) % 3
        if phase == 0:
            if water_f is None:
                return "WATER --", P["lgray"]
            return "WATER %.1fF" % water_f, P["lblue"] if water_f < WATER_RANGE[0] else (P["lred"] if water_f > WATER_RANGE[1] else P["lcyan"])
        if phase == 1:
            return ("AIR %.1fF" % air_f) if air_f is not None else "AIR --", P["white"]
        return ("HUM %d%%" % hum) if hum is not None else "HUM --", P["white"]
    label, status, temp_f, up, why = item[1]
    pen = P[STATUS[status]]
    if status == "down":
        return label + (" DOWN" if not second else " NO SIG"), pen
    if status is None:
        return label + " ???", pen
    if not second:
        return "%s %s" % (label, "--" if up is None else ("100%" if up >= 0.9995 else "%.1f%%" % (up * 100))), pen
    text = "%s %s" % (label, ("%dF" % temp_f) if temp_f is not None else "OK")
    if status == "warn" and why:
        text = "%s %s" % (label, why)
    return text, pen


# ---------------------------------------------------------------- foreground
CAR = (".....CH......",
       "...RRRRRRRR..",
       "TRRRRRRRRRRRY",
       "RRRRRRRRRRRRR",
       ".WWW.....WWW.")


def draw_car(t):
    g = _gfx
    bounce = 1 if (t // 230) % 5 == 0 else 0
    pens = {"C": P["lcyan"], "H": P["yellow"], "R": P["lred"], "T": P["red"], "Y": P["yellow"], "W": P["lgray"]}
    x0 = 2
    g.set_pen(P["black"])  # backing so the car doesn't melt into the road lines
    g.rectangle(x0 - 1, HZ - 1, len(CAR[0]) + 2, 5)
    for r, row in enumerate(CAR):
        y = HZ - 1 + r - (bounce if r < 4 else 0)
        for c, ch in enumerate(row):
            pen = pens.get(ch)
            if pen is not None:
                if ch == "W" and (t // 60 + c) % 3 == 0:
                    pen = P["dgray"]  # spinning wheels
                g.set_pen(pen)
                g.pixel(x0 + c, y)


def draw_palms(t):
    g = _gfx
    off = (t * PALM_PXS // 1000) % 70
    for base in (70, 105):
        x = base - off
        x = x if x > -6 else x + 70
        if -5 <= x < 58:
            g.set_pen(P["brown"])
            g.rectangle(x, 3, 1, 8)
            g.set_pen(P["green"])
            for dx, dy in ((-3, 3), (-2, 2), (-1, 2), (1, 2), (2, 2), (3, 3), (-1, 1), (0, 1), (1, 1)):
                g.pixel(x + dx, dy + 1)


# ---------------------------------------------------------------- frame
WATER_RANGE = [74, 82]  # F; frame() takes it from main.py's config


def frame(gfx, ms, info):
    init(gfx)
    WATER_RANGE[:] = info.get("water_range", WATER_RANGE)
    gfx.set_pen(P["black"])
    gfx.clear()
    items = [("host", h) for h in info["hosts"][:2]] + [("tank", info["tank"])] + \
            [("host", h) for h in info["hosts"][2:]]
    loop = SPACING * len(items)
    scroll = ms * SCENERY_PXS // 1000
    sky_and_sun(ms)
    focus = None
    for i, item in enumerate(items):
        cx = (i * SPACING - scroll) % loop + 8
        for x in (cx, cx - loop):
            if -10 < x < 63:
                lit = abs(x - FOCUS_X) <= 9
                draw_landmark(item, x, ms, lit)
                if lit:
                    focus = item
    road(ms)
    draw_car(ms)
    draw_palms(ms)
    if focus:
        text, pen = readout(focus, ms)
        tiny(text, 1, 0, pen)
