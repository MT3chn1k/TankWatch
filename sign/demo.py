"""1990s demoscene loop for the Galactic Unicorn showing the health of the TankWatch collectors.

Scenes, in order, then repeat:
  1. Starfield intro, the four host tags typing in, each in its status colour
  2. Plasma with a sine scroller: per-host status, CPU temp (F) and 24 h uptime
  3. Copper bars: one raster bar per host bouncing across, coloured by status
  4. Fire: four flames, one per host; healthy burns tall and green, warning amber, down is red embers
Status colours match the rest of the display: green up, amber warning, red down, grey unknown.

main.py calls frame(gfx, ms, hosts) once per display update; hosts is a list of
(label, status, temp_f or None, uptime 0-1 or None, reason or None).
"""
import math
import random
import micropython

W, H = 53, 11

SIN = bytearray(int(128 + 127 * math.sin(i * 2 * math.pi / 256)) for i in range(256))

_gfx = None
P = {}


def _ramp(stops, n):
    """n pens blended through the (r, g, b) stops."""
    out = []
    for i in range(n):
        f = i * (len(stops) - 1) / (n - 1)
        a = int(f)
        b = min(a + 1, len(stops) - 1)
        t = f - a
        c = [int(stops[a][k] + (stops[b][k] - stops[a][k]) * t) for k in range(3)]
        out.append(_gfx.create_pen(*c))
    return out


STATUS_RGB = {"up": (0, 200, 50), "warn": (240, 150, 0), "down": (220, 0, 0), None: (110, 110, 110)}


def init(gfx):
    global _gfx
    if _gfx is gfx:
        return
    _gfx = gfx
    P["black"] = gfx.create_pen(0, 0, 0)
    P["white"] = gfx.create_pen(255, 255, 255)
    P["shadow"] = gfx.create_pen(0, 0, 30)
    P["water"] = gfx.create_pen(0, 190, 255)
    for s, rgb in STATUS_RGB.items():
        P[s] = gfx.create_pen(*rgb)
    # dim plasma so the scroller reads on top of it
    P["plasma"] = _ramp([(20, 0, 40), (0, 30, 90), (60, 0, 70), (90, 20, 0), (20, 0, 40)], 64)
    P["stars"] = _ramp([(15, 15, 30), (90, 90, 140), (255, 255, 255)], 16)
    P["copper"] = _ramp([(0, 0, 0), (0, 0, 60), (40, 0, 90), (0, 0, 60), (0, 0, 0)], 32)
    P["fire"] = {
        "up": _ramp([(0, 0, 0), (0, 40, 0), (0, 150, 20), (120, 230, 40), (230, 255, 180)], 32),
        "warn": _ramp([(0, 0, 0), (60, 10, 0), (200, 80, 0), (255, 170, 0), (255, 240, 150)], 32),
        "down": _ramp([(0, 0, 0), (50, 0, 0), (140, 0, 0), (220, 20, 0), (255, 60, 0)], 32),
        None: _ramp([(0, 0, 0), (30, 30, 30), (90, 90, 90), (150, 150, 150), (200, 200, 200)], 32),
    }
    P["donut"] = {s: _ramp([(0, 0, 0), tuple(c // 3 for c in rgb), rgb, (255, 255, 255)], 16)
                  for s, rgb in STATUS_RGB.items()}
    for s, rgb in STATUS_RGB.items():  # raster bar: dark edge, bright centre, white-hot core
        r, g, b = rgb
        P["bar_" + str(s)] = [gfx.create_pen(r * k // 8, g * k // 8, b * k // 8) for k in (2, 4, 6, 8)] + \
                             [gfx.create_pen(min(255, r + 120), min(255, g + 120), min(255, b + 120))]


# ---------------------------------------------------------------- helpers
def _text(s, x, y, pen, shadow=True):
    if shadow:
        _gfx.set_pen(P["shadow"])
        _gfx.text(s, x + 1, y + 1, -1, 1)
    _gfx.set_pen(pen)
    _gfx.text(s, x, y, -1, 1)


def _status_text(h):
    label, status, temp_f, up, why = h
    if status is None:
        return "%s ???" % label
    if status == "down":
        return "%s DOWN!" % label
    word = why if status == "warn" and why else "OK"
    parts = [label, word]
    if temp_f is not None:
        parts.append("%dF" % temp_f)
    if up is not None:
        parts.append("UP %s" % ("100%" if up >= 0.9995 else "%.1f%%" % (up * 100)))
    return " ".join(parts)


# ---------------------------------------------------------------- scene 1: starfield + tags typing in
STARS = [[random.getrandbits(8) - 128, random.getrandbits(6) - 32, random.getrandbits(8) + 1] for _ in range(28)]


@micropython.native
def _stars(speed):
    g = _gfx
    pens = P["stars"]
    step = speed * _seq["dt"] // 40
    for s in STARS:
        s[2] -= step
        if s[2] <= 1:
            s[0] = random.getrandbits(8) - 128
            s[1] = random.getrandbits(6) - 32
            s[2] = 255
        sx = 26 + s[0] * 24 // s[2]
        sy = 5 + s[1] * 24 // s[2]
        if 0 <= sx < 53 and 0 <= sy < 11:
            g.set_pen(pens[15 - s[2] // 17])
            g.pixel(sx, sy)


def scene_intro(t, hosts):
    _gfx.set_font("bitmap6")
    _stars(6)
    shown = t // 350  # one more tag every 0.35 s
    gap = 3
    x = (W - sum(_gfx.measure_text(h[0], 1) for h in hosts) - gap * (len(hosts) - 1)) // 2
    for i, h in enumerate(hosts):
        if i < shown:
            # the tag just typed flashes white for a moment
            pen = P["white"] if i == shown - 1 and t % 350 < 120 and shown <= len(hosts) else P[h[1]]
            _text(h[0], x, 3, pen)
        x += _gfx.measure_text(h[0], 1) + gap
    return t > 4500


# ---------------------------------------------------------------- scene 2: plasma + sine scroller
@micropython.native
def _plasma(t):
    g = _gfx
    pens = P["plasma"]
    t1 = t // 20
    t2 = t // 33
    t3 = t // 47
    for y in range(11):
        sy = SIN[(y * 14 + t2) & 255]
        for x in range(53):
            v = SIN[(x * 7 + t1) & 255] + sy + SIN[((x + y) * 5 - t3) & 255]
            g.set_pen(pens[(v * 64 // 768) & 63])
            g.pixel(x, y)


_scroll = {"chars": None, "t0": 0}
_tank = [None]  # (air_f, humidity, water_f) from main.py


def _tank_segments():
    if not _tank[0]:
        return []
    air_f, hum, water_f = _tank[0]
    segs = [("WATER %.1fF" % water_f if water_f is not None else "WATER --", P["water"])]
    air = "AIR %.1fF" % air_f if air_f is not None else "AIR --"
    if hum is not None:
        air += " %d%%" % hum
    segs.append((air, P["white"]))
    return segs


def scene_scroller(t, hosts):
    _plasma(t)
    _gfx.set_font("bitmap6")
    if _scroll["chars"] is None:
        chars = []
        for seg, pen in [("*** FISH TANK CREW STATUS REPORT ***", P["white"])] + \
                        [(_status_text(h), P[h[1]]) for h in hosts] + _tank_segments() + \
                        [("GREETZ TO GUPPY, TETRA & PLECO", P["white"])]:
            for ch in seg + "   ":
                chars.append((ch, pen, _gfx.measure_text(ch, 1)))
        _scroll["chars"] = chars
        _scroll["t0"] = t
    x = W - (t - _scroll["t0"]) * 25 // 1000  # 25 px/s whatever the frame rate
    for ch, pen, w in _scroll["chars"]:
        if x > W:
            break
        if x > -w and ch != " ":
            y = 2 + (SIN[(x * 3 + t // 8) & 255] - 128) * 2 // 128  # gentle +-2 row wave across the text
            _text(ch, x, y, pen)
        x += w
    if x < 0:
        _scroll["chars"] = None
        return True
    return False


# ---------------------------------------------------------------- scene 3: copper bars
@micropython.native
def _copper_bg(t):
    g = _gfx
    pens = P["copper"]
    for y in range(11):
        g.set_pen(pens[(y * 3 + t // 40) & 31])
        g.rectangle(0, y, 53, 1)


def scene_copper(t, hosts):
    _copper_bg(t)
    _gfx.set_font("bitmap6")
    order = []
    for i, h in enumerate(hosts):
        phase = (t // 9 + i * 64) & 255
        cx = 3 + (SIN[phase] * 46) // 255
        depth = SIN[(phase + 64) & 255]  # front/back of the swing decides who's drawn on top
        order.append((depth, cx, h))
    order.sort(key=lambda o: o[0])
    for depth, cx, h in order:
        pens = P["bar_" + str(h[1])]
        for dx, k in ((-3, 0), (-2, 1), (-1, 2), (0, 4), (1, 2), (2, 1), (3, 0)):
            _gfx.set_pen(pens[k] if k < 4 else pens[4])
            _gfx.rectangle(cx + dx, 0, 1, 11)
        if depth > 128:  # tag rides on bars in front
            w = _gfx.measure_text(h[0], 1)
            _text(h[0], cx - w // 2, 3, P["white"])
    return t > 8000


# ---------------------------------------------------------------- scene 4: four flames
FW, FH = 53, 14
HEAT = bytearray(FW * FH)
FUEL = {"up": (200, 255), "warn": (110, 190), "down": (60, 130), None: (60, 150)}  # tall / two-thirds / embers


@micropython.native
def _fire_step(lo0, hi0, lo1, hi1, lo2, hi2, lo3, hi3):
    heat = HEAT
    base = (FH - 1) * FW
    lo = (lo0, lo1, lo2, lo3)
    hi = (hi0, hi1, hi2, hi3)
    for x in range(FW):
        z = x * 4 // FW
        if x % 13 == 0:
            heat[base + x] = 0  # dark gap between the four flames
        else:
            heat[base + x] = lo[z] + random.getrandbits(8) * (hi[z] - lo[z]) // 256
    for y in range(FH - 1):
        row = y * FW
        below = row + FW
        for x in range(1, FW - 1):
            v = (heat[below + x - 1] + heat[below + x] * 2 + heat[below + x + 1]) // 4
            v -= 10 + random.getrandbits(3)
            heat[row + x] = v if v > 0 else 0


@micropython.native
def _fire_draw(p0, p1, p2, p3):
    g = _gfx
    heat = HEAT
    zones = (p0, p1, p2, p3)
    for y in range(11):
        row = (y + 1) * FW
        for x in range(53):
            g.set_pen(zones[x * 4 // 53][heat[row + x] >> 3])
            g.pixel(x, y)


def scene_fire(t, hosts):
    f = [FUEL[h[1]] for h in hosts]
    while _seq["fire"] <= t:  # 25 steps a second whatever the frame rate
        _fire_step(f[0][0], f[0][1], f[1][0], f[1][1], f[2][0], f[2][1], f[3][0], f[3][1])
        _seq["fire"] += 40
        if t - _seq["fire"] > 400:
            _seq["fire"] = t
    pal = P["fire"]
    _fire_draw(pal[hosts[0][1]], pal[hosts[1][1]], pal[hosts[2][1]], pal[hosts[3][1]])
    _gfx.set_font("bitmap6")
    for i, h in enumerate(hosts):
        w = _gfx.measure_text(h[0], 1)
        _text(h[0], i * 13 + 7 - w // 2, 0, P["white"])
    return t > 8000


# ---------------------------------------------------------------- scene 5: hyper donut (after Crystal Dream 2)
# A shaded dot torus. Its ring is split in four quarters, one per collector, each in its status colour;
# the host whose quarter faces you is named on the right.
TU, TV = 28, 10
TOR = []  # x, y, z, nx, ny, nz, quarter
for _i in range(TU):
    _u = _i * 2 * math.pi / TU
    for _j in range(TV):
        _v = _j * 2 * math.pi / TV
        _nx, _ny, _nz = math.cos(_u) * math.cos(_v), math.sin(_u) * math.cos(_v), math.sin(_v)
        TOR.append((math.cos(_u) * 1.0 + 0.45 * _nx, math.sin(_u) * 1.0 + 0.45 * _ny, 0.45 * _nz, _nx, _ny, _nz, _i * 4 // TU))
ZBUF = bytearray(W * H)


@micropython.native
def _donut(t, p0, p1, p2, p3):
    g = _gfx
    zb = ZBUF
    for i in range(W * H):
        zb[i] = 0
    a = t * 0.0011
    b = t * 0.0007
    ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
    pens = (p0, p1, p2, p3)
    front = [0.0, 0.0, 0.0, 0.0]
    for x, y, z, nx, ny, nz, q in TOR:
        # rotate about X (a) then Y (b)
        y1 = y * ca - z * sa
        z1 = y * sa + z * ca
        x2 = x * cb + z1 * sb
        z2 = -x * sb + z1 * cb
        ny1 = ny * ca - nz * sa
        nz1 = ny * sa + nz * ca
        nx2 = nx * cb + nz1 * sb
        nz2 = -nx * sb + nz1 * cb
        depth = z2 + 3.2
        sx = int(14 + x2 * 16 / depth)
        sy = int(5.5 + y1 * 16 / depth)
        if 0 <= sx < 53 and 0 <= sy < 11:
            zz = int(255 - depth * 50)
            k = sy * 53 + sx
            if zz > zb[k]:
                zb[k] = zz
                light = (nx2 * -0.4 + ny1 * -0.5 + nz2 * -0.75)  # light from upper left, towards viewer
                lv = int(2 + light * 13) if light > 0 else 2
                g.set_pen(pens[q][lv if lv < 16 else 15])
                g.pixel(sx, sy)
        front[q] -= z2
    best = 0
    for q in range(4):
        if front[q] > front[best]:
            best = q
    return best


def scene_donut(t, hosts):
    pal = P["donut"]
    q = _donut(t, pal[hosts[0][1]], pal[hosts[1][1]], pal[hosts[2][1]], pal[hosts[3][1]])
    h = hosts[q]
    _gfx.set_font("bitmap6")
    _text(h[0], 31, 0, P[h[1]], shadow=False)
    _tiny(_host_word(h)[len(h[0]) + 1:], 31, 6, P["white"])
    return t > 10000


# ---------------------------------------------------------------- scene 6: dot-morph text (after Crystal Dream 2)
# Each status word is built from 2x2 dots; between words the dots explode and fly to their new places.
FONT3 = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "K": "101101110101101", "L": "100100100100111", "M": "101111111101101",
    "N": "110101101101101", "O": "010101101101010", "P": "110101110100100", "R": "110101110101101",
    "S": "011100010001110", "T": "111010010010010", "U": "101101101101111", "V": "101101101101010",
    "W": "101101111111101", "?": "110001010000010", "!": "010010010000010", "0": "111101101101111",
    "1": "010110010010111", "2": "110001010100111", "3": "110001010001110", "4": "101101111001001",
    "5": "111100110001110", "6": "011100111101111", "7": "111001010010010", "8": "111101111101111",
    "9": "111101111001110", "%": "101001010100101",
    ".": "000000000000010", "-": "000000111000000", ":": "000010000010000", "$": "011110010011110",
    "J": "001001001101010", "Q": "010101101110011", "X": "101101010101101", "Y": "101101010010010",
    "Z": "111001010100111",
}
NDOTS = 120
DOTS = [[random.getrandbits(6) - 5, random.getrandbits(4) - 2] for _ in range(NDOTS)]  # current x, y
_morph = {"word": -1, "src": None, "dst": None}


def _word_targets(s):
    pts = []
    x = (W - (len(s) * 7 - 1)) // 2
    for ch in s:
        bits = FONT3.get(ch)
        if bits:
            for k in range(15):
                if bits[k] == "1":
                    pts.append((x + (k % 3) * 2, (k // 3) * 2))
        x += 7
    return pts


def _tiny(s, x, y, pen):
    """3x5 text, 4 px per character."""
    _gfx.set_pen(pen)
    for ch in s:
        bits = FONT3.get(ch)
        if bits:
            for k in range(15):
                if bits[k] == "1":
                    _gfx.pixel(x + k % 3, y + k // 3)
        x += 4


def _host_word(h):
    if h[1] == "down":
        return h[0] + " DOWN"
    if h[1] is None:
        return h[0] + " ???"
    if h[1] == "warn":
        return h[0] + " " + (h[4] or "WARN")
    return h[0] + " OK"


@micropython.native
def _dots(src, dst, f, pen, t):
    g = _gfx
    g.set_pen(pen)
    n = len(dst)
    for i in range(NDOTS):
        sx, sy = src[i]
        if i < n:
            tx, ty = dst[i]
        else:
            tx, ty = 26 + (i * 37 % 60) - 30, -6  # spare dots park above the screen
        # ease in-out, with a swirl that peaks mid-flight
        e = f * f * (3 - 2 * f)
        sw = math.sin(f * math.pi) * 9
        x = sx + (tx - sx) * e + math.sin(i * 0.7 + t * 0.004) * sw
        y = sy + (ty - sy) * e + math.cos(i * 1.3 + t * 0.003) * sw * 0.4
        g.rectangle(int(x), int(y), 2, 2)


def scene_morph(t, hosts):
    step = 2200  # 900 ms flight + 1300 ms hold per word
    w = t // step
    if w >= len(hosts):
        _morph["word"] = -1
        return True
    if w != _morph["word"]:
        _morph["word"] = w
        _morph["src"] = [(d[0], d[1]) for d in DOTS]
        dst = _word_targets(_host_word(hosts[w]))
        random.seed(w)  # same shuffle each lap, different per word
        for i in range(len(dst) - 1, 0, -1):
            j = random.getrandbits(8) % (i + 1)
            dst[i], dst[j] = dst[j], dst[i]
        _morph["dst"] = dst[:NDOTS]
    f = min(1.0, (t % step) / 900)
    src, dst = _morph["src"], _morph["dst"]
    _stars(3)
    _dots(src, dst, f, P[hosts[w][1]], t)
    for i in range(NDOTS):  # remember where every dot is for the next explosion
        if f >= 1.0:
            DOTS[i][0], DOTS[i][1] = (dst[i] if i < len(dst) else (26 + (i * 37 % 60) - 30, -6))
    return False


# ---------------------------------------------------------------- sequencer
SCENES = [scene_intro, scene_scroller, scene_donut, scene_copper, scene_morph, scene_fire]
_seq = {"i": 0, "start": None, "last": None, "dt": 40, "fire": 0}


def restart():
    _seq["i"], _seq["start"], _seq["last"], _seq["fire"] = 0, None, None, 0
    _scroll["chars"] = None


def frame(gfx, ms, hosts, tank=None):
    """tank: (air_f, humidity, water_f), each None when missing; shown in the scroller."""
    init(gfx)
    _tank[0] = tank
    if _seq["start"] is None:
        _seq["start"] = ms
    dt = 40 if _seq["last"] is None else ms - _seq["last"]
    _seq["dt"] = dt if 0 < dt < 200 else 40
    _seq["last"] = ms
    t = ms - _seq["start"]
    if t < 0:
        t = 0
    gfx.set_pen(P["black"])
    gfx.clear()
    done = SCENES[_seq["i"]](t, hosts)
    if t < 80:  # classic white flash between scenes
        gfx.set_pen(P["white"])
        gfx.clear()
    if done:
        _seq["i"] = (_seq["i"] + 1) % len(SCENES)
        _seq["start"] = ms
        _seq["fire"] = 0
