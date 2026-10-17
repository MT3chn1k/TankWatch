"""Road Rash (1991) style race for the TankWatch status sign that reports the collectors and readings. EGA palette.

You ride against each collector (N1, N2, HUB ...), rival bikers in their status colours (bright green up, yellow
warning, bright red down, grey unknown). The action and the numbers take turns so each is easy to follow:
  approach  the rival grows out of the horizon; its tag (N1...) sits in the top-left corner
  fight     big 7x6 bikes side by side trading punches: white hit flashes and sparks, no text
  knockout  rider and bike go flying into the grass
  card      a full-screen pit board slides in: "N1 UP 100%" / "CPU 128F" (plus HOT / LOWV / THRT)
A down host is a wreck on the shoulder, a roadside sign brings the water and air readings, your position counts
down from 5TH as you pass them, and the race ends with results cards ranked by uptime.

main.py calls frame(gfx, ms, info) once per display update; info is
{"hosts": [(label, status, temp_f, uptime, why), ...], "tank": (air_f, humidity, water_f)} (each None when missing or stale).
"""
import math
import micropython
from demo import FONT3

W, H = 53, 11
HOR = 3                 # first road row; rows 0-2 are sky
ROWS = H - HOR          # 8 road rows
CX = 26                 # road centre at the bottom row, where the player rides
NEAR = 8.0              # world distance of the bottom row (p = 1)

EGA = {"black": (0, 0, 0), "blue": (0, 0, 170), "green": (0, 170, 0), "cyan": (0, 170, 170),
       "red": (170, 0, 0), "magenta": (170, 0, 170), "brown": (170, 85, 0), "lgray": (170, 170, 170),
       "dgray": (85, 85, 85), "lblue": (85, 85, 255), "lgreen": (85, 255, 85), "lcyan": (85, 255, 255),
       "lred": (255, 85, 85), "lmagenta": (255, 85, 255), "yellow": (255, 255, 85), "white": (255, 255, 255)}
STATUS = {"up": "lgreen", "warn": "yellow", "down": "lred", None: "lgray"}

_gfx = None
P = {}


def init(gfx):
    global _gfx
    if _gfx is gfx:
        return
    _gfx = gfx
    for k, rgb in EGA.items():
        P[k] = gfx.create_pen(*rgb)
    for s, k in STATUS.items():
        P[s] = P[k]


# ---------------------------------------------------------------- text
def tiny(s, x, y, pen):
    """3x5 text, 4 px per character."""
    g = _gfx
    g.set_pen(pen)
    for ch in s:
        bits = FONT3.get(ch)
        if bits:
            for k in range(15):
                if bits[k] == "1":
                    g.pixel(x + k % 3, y + k // 3)
        x += 4


def tiny_w(s):
    return len(s) * 4 - 1


def big(s, pen, y=1):
    g = _gfx
    g.set_font("bitmap8")
    w = g.measure_text(s, 1)
    x = (W - w) // 2
    g.set_pen(P["black"])
    g.text(s, x + 1, y + 1, -1, 1)
    g.set_pen(pen)
    g.text(s, x, y, -1, 1)


def card(rel, bar, line1, pen1, line2, pen2):
    """Full-screen pit board: status bar on the left, two lines of text. Slides in from the right."""
    g = _gfx
    dx = 0 if rel >= 150 else W - W * rel // 150
    g.set_pen(P["black"])
    g.clear()
    g.set_pen(bar)
    g.rectangle(dx, 0, 2, 11)
    tiny(line1, dx + 4, 0, pen1)
    tiny(line2, dx + 4, 6, pen2)


# ---------------------------------------------------------------- road
def road_cx(p, curve):
    q = 1 - p
    return CX + curve * q * q * 22


def road_half(p):
    return 1 + p * 24


@micropython.native
def _dither_row(y, x0, x1, pen, phase):
    g = _gfx
    g.set_pen(pen)
    x = x0 + ((x0 + y + phase) & 1)
    while x <= x1:
        g.pixel(x, y)
        x += 2


@micropython.native
def draw_road(pos, curve, finish_d):
    g = _gfx
    # sky: blue over light blue, a brown ridge that slides against the bends, a yellow sun
    g.set_pen(P["blue"])
    g.rectangle(0, 0, 53, 1)
    g.set_pen(P["lblue"])
    g.rectangle(0, 1, 53, 2)
    shift = int(curve * 9)
    g.set_pen(P["yellow"])
    g.rectangle(41 - shift, 0, 2, 2)
    for x in range(53):
        u = x + shift
        hgt = int(1.2 + math.sin(u * 0.21) + 0.6 * math.sin(u * 0.08 + 1))
        if hgt > 0:
            g.set_pen(P["brown"] if hgt < 2 else P["dgray"])
            g.rectangle(x, HOR - (2 if hgt > 2 else hgt), 1, 2 if hgt > 2 else hgt)
    for y in range(HOR, 11):
        p = (y - HOR + 1) / 8
        d = NEAR / p
        # 4-unit stripes: each edge slides down the rows toward you. Rows near the horizon span more
        # than a stripe and would only flicker, so they stay plain.
        band = (int((d + pos) * 0.25) & 1) if p > 0.3 else 0
        cx = road_cx(p, curve)
        half = road_half(p)
        l = int(cx - half)
        r = int(cx + half)
        g.set_pen(P["green"])
        g.rectangle(0, y, 53, 1)
        g.set_pen(P["dgray"])
        g.rectangle(l, y, r - l + 1, 1)
        if band:  # EGA-style dithered bands give the sense of speed
            _dither_row(y, 0, l - 1, P["black"], 0)
            _dither_row(y, r + 1, 52, P["black"], 0)
            _dither_row(y, l + 2, r - 2, P["black"], 1)
        g.set_pen(P["red"] if band else P["white"])
        g.pixel(l, y)
        g.pixel(r, y)
        if p > 0.4:
            g.pixel(l + 1, y)
            g.pixel(r - 1, y)
        if not band and p > 0.25:
            g.set_pen(P["yellow"])
            g.pixel(int(cx), y)
        if finish_d > 0 and abs(d - finish_d) < 1.0 + d * 0.06:
            for x in range(l, r + 1):
                g.set_pen(P["white"] if ((x + y) & 1) else P["black"])
                g.pixel(x, y)


def to_screen(d, lane, curve):
    """World distance + lane (-1 left edge .. +1 right edge) -> screen x, y (bottom row of sprite), scale p."""
    p = NEAR / d
    if p < 1 / ROWS or p > 1.2:
        return None
    y = HOR - 1 + p * ROWS
    return road_cx(p, curve) + lane * road_half(p), y, p


# ---------------------------------------------------------------- sprites
# Rear view, 7 wide x 6 tall, bottom row = tyre. H helmet, J jacket, G glove, B bike, R tail light, T tyre
BIKER = ("..HHH..",
         "..HHH..",
         ".JJJJJ.",
         "GJJJJJG",
         "..BRB..",
         "..BTB..")
BIKER_MID = (".H.", "JJJ", ".B.", ".T.")
WRECK = ("..JH...",     # rider sprawled beside the bike lying on its side
         "TBBBBT.")


def _blit(rows, x, y, pens, outline=False):
    g = _gfx
    h = len(rows)
    if outline:  # black 1 px border so a sprite reads against grass of the same colour
        g.set_pen(P["black"])
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch in pens:
                    yy = y - h + 1 + r
                    g.pixel(x + c - 1, yy)
                    g.pixel(x + c + 1, yy)
                    g.pixel(x + c, yy - 1)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            pen = pens.get(ch)
            if pen is not None:
                g.set_pen(pen)
                g.pixel(x + c, y - h + 1 + r)


def draw_biker(x, y, p, jacket, helmet, lean=0, punch=0, flash=False, smoke=False, t=0):
    x, y = int(x + 0.5), int(y + 0.5)
    g = _gfx
    if smoke:
        for k in range(3):
            if (t // 110 + k) % 3:
                g.set_pen(P["lgray"] if k == 0 else P["dgray"])
                g.pixel(x - 1 + (k - 1) * 2 + ((t // 80 + k) & 1), y + 1 - k)
    if flash:
        jacket = helmet = P["white"]
    if p < 0.4:
        g.set_pen(jacket)
        g.pixel(x, y - 1)
        g.set_pen(P["dgray"])
        g.pixel(x, y)
        return
    if p < 0.75:
        _blit(BIKER_MID, x - 1, y, {"H": helmet, "J": jacket, "B": P["lgray"], "T": P["black"]}, outline=True)
        return
    pens = {"H": helmet, "J": jacket, "G": P["lgray"], "B": P["lgray"], "R": P["lred"], "T": P["black"]}
    _blit(BIKER[:4], x - 3 + lean, y - 2, pens, outline=True)
    _blit(BIKER[4:], x - 3, y, pens, outline=True)
    if punch:
        g.set_pen(P["lgray"])
        for k in range(2, 5):
            g.pixel(x + punch * (2 + k) + lean, y - 2)


def draw_wreck(x, y, p, t):
    x, y = int(x), int(y)
    flash = P["lred"] if (t // 250) & 1 else P["red"]
    if p < 0.5:
        _gfx.set_pen(flash)
        _gfx.pixel(x, y)
        return
    _blit(WRECK, x - 3, y, {"J": flash, "H": P["white"], "B": P["lgray"], "T": P["black"]})


def draw_sign(x, y, p):
    g = _gfx
    x, y = int(x), int(y)
    w = 1 if p < 0.4 else (3 if p < 0.75 else 7)
    hgt = 1 if p < 0.4 else (2 if p < 0.75 else 3)
    g.set_pen(P["brown"])
    g.rectangle(x, y - 1, 1, 2)
    if w == 7:
        g.rectangle(x - 3, y - 1, 1, 2)
    g.set_pen(P["white"])
    g.rectangle(x - w // 2 - (1 if w == 7 else 0), y - 1 - hgt, w, hgt)
    if w == 7:
        g.set_pen(P["blue"])
        g.rectangle(x - 3, y - 3, 5, 1)


def draw_tree(x, y, p):
    g = _gfx
    x, y = int(x), int(y)
    if p < 0.35:
        g.set_pen(P["green"])
        g.pixel(x, y - 1)
        return
    hgt = 2 if p < 0.7 else 5
    g.set_pen(P["brown"])
    g.rectangle(x, y - 1, 1, 2)
    g.set_pen(P["lgreen"] if hgt == 5 else P["green"])
    g.rectangle(x - 1, y - hgt, 3, hgt - 1)


def draw_spark(x, y, t):
    g = _gfx
    g.set_pen(P["yellow"] if (t // 50) & 1 else P["white"])
    for dx, dy in ((0, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        g.pixel(x + dx, y + dy)


# ---------------------------------------------------------------- race script
APPROACH = 2000   # rival comes from the horizon to alongside
FIGHT = 2000      # side by side trading punches
KO = 900          # rider and bike fly off
CARD = 2300       # pit board with the numbers
WRECK_PASS = 2600
SIGN_PASS = 2600
HITS = (250, 850, 1450)     # player's punches land, ms into the fight
COUNTERS = (550, 1150)      # rival swings back
RIVAL_LANE = 0.47


def _ordinal(n):
    return {1: "1ST", 2: "2ND", 3: "3RD"}.get(n, "%dTH" % n)


def _uptime(u):
    if u is None:
        return "--"
    return "100%" if u >= 0.9995 else "%.1f%%" % (u * 100)


# Colour bands in F (blue below, green inside, red above); frame() takes them from main.py's config
AIR_RANGE = [68, 80]
WATER_RANGE = [74, 82]


def _temp_pen(f):
    return P["lblue"] if f < AIR_RANGE[0] else (P["lred"] if f > AIR_RANGE[1] else P["lgreen"])


def _water_pen(f):
    return P["lblue"] if f < WATER_RANGE[0] else (P["lred"] if f > WATER_RANGE[1] else P["lgreen"])


def build_events(info):
    ev = []
    t = 3200  # after the countdown
    for i, h in enumerate(info["hosts"]):
        if h[1] == "down":
            ev.append((t, "wreck", h))
            t += WRECK_PASS + CARD
        else:
            ev.append((t, "rival", h))
            t += APPROACH + FIGHT + KO + CARD
        if i == 1:
            ev.append((t, "sign", info["tank"]))
            t += SIGN_PASS + CARD
    ev.append((t, "finish", None))
    return ev, t + 2400


race = {"events": None, "end": 0, "start": None, "pos": 0.0, "last": None, "info": None}


def restart():
    race.update(events=None, start=None, last=None)


def _curve_at(t):
    return math.sin(t * 0.00031) * 0.8 + math.sin(t * 0.00077) * 0.35


def _trees(pos, curve):
    base = int(pos / 9) * 9
    for k in range(7, 0, -1):
        d = base + k * 9 - pos + NEAR * 0.95
        side = -1.5 if (int((base + k * 9) / 9) & 1) else 1.5
        s = to_screen(d, side, curve)
        if s:
            draw_tree(*s)


def _approach_d(f, p_end):
    return NEAR / (1 / ROWS + (p_end - 1 / ROWS) * f * f)


def frame(gfx, ms, info):
    init(gfx)
    AIR_RANGE[:] = info.get("air_range", AIR_RANGE)
    WATER_RANGE[:] = info.get("water_range", WATER_RANGE)
    if race["start"] is None:
        race["start"] = ms
        race["events"], race["end"] = build_events(info)
        race["info"] = info
        race["pos"] = 0.0
    t = ms - race["start"]
    dt = 0 if race["last"] is None else max(0, min(200, ms - race["last"]))
    race["last"] = ms
    info = race["info"]  # numbers frozen for the whole race so the story stays consistent
    hosts = info["hosts"]

    if t >= race["end"]:
        if results(t - race["end"], info):
            restart()
        return

    speed = 0.0 if t < 3000 else min(1.0, (t - 3000) / 800)
    passed = 0
    finish_d = 0.0
    sprites = []        # (distance, draw function), painted far to near
    tag = None          # top-left nametag for the rival coming up
    show_card = None    # (rel, bar, line1, pen1, line2, pen2)
    punch = 0
    paused = False      # the road stops scrolling while a card is up

    for start, kind, data in race["events"]:
        rel = t - start
        if rel < 0:
            continue
        if kind == "rival":
            label, status, temp_f, up, why = data
            pen = P[status]
            cpu = "CPU %dF" % temp_f if temp_f is not None else "CPU --"
            if status == "warn" and why:
                cpu += " " + why
            if rel < APPROACH:
                d = _approach_d(rel / APPROACH, 0.97)
                s = to_screen(d, RIVAL_LANE, 0)
                tag = (label, pen)
                if s:
                    sprites.append((d, lambda s=s, pen=pen, st=status, rl=rel: draw_biker(
                        s[0], s[1], s[2], pen, P["lgray"], smoke=(st == "warn"), t=rl)))
            elif rel < APPROACH + FIGHT:
                fr = rel - APPROACH
                s = to_screen(NEAR / 0.97, RIVAL_LANE, 0)
                hit = any(0 <= fr - h < 90 for h in HITS)
                swing = any(0 <= fr - c < 180 for c in COUNTERS)
                if any(0 <= fr - h < 200 for h in HITS):
                    punch = 1
                bob = 1 if (fr // 160) & 1 else 0
                sprites.append((NEAR / 0.97, lambda s=s, pen=pen, st=status, fr=fr, hit=hit, swing=swing, bob=bob: (
                    draw_biker(s[0] + bob, s[1], 1.0, pen, P["lgray"], punch=-1 if swing else 0,
                               flash=hit, smoke=(st == "warn"), t=fr),
                    draw_spark(int(s[0]) - 4, int(s[1]) - 3, fr) if hit else None)))
            elif rel < APPROACH + FIGHT + KO:
                f = (rel - APPROACH - FIGHT) / KO
                s = to_screen(NEAR / 0.97, RIVAL_LANE, 0)
                x0, y0 = int(s[0]), int(s[1])
                # bike skids off to the right, rider arcs up and over it
                sprites.append((NEAR, lambda x0=x0, y0=y0, f=f, pen=pen: (
                    _blit(("TBBBT",), x0 - 2 + int(f * 14), y0, {"T": P["black"], "B": P["lgray"]}),
                    _blit(("H", "J"), x0 + int(f * 10), y0 - 2 - int(math.sin(f * math.pi) * 5),
                          {"H": P["lgray"], "J": pen}))))
            elif rel < APPROACH + FIGHT + KO + CARD:
                show_card = (rel - APPROACH - FIGHT - KO, pen, "%s UP %s" % (label, _uptime(up)), pen,
                             cpu, P["yellow"] if status == "warn" else P["white"])
            else:
                passed += 1
        elif kind == "wreck":
            label, status, temp_f, up, why = data
            if rel < WRECK_PASS:
                f = rel / WRECK_PASS
                d = _approach_d(f, 1.15)
                s = to_screen(d, -0.8, 0)
                tag = (label, P["lred"] if (rel // 300) & 1 else P["white"])
                if s:
                    sprites.append((d, lambda s=s, rl=rel: draw_wreck(s[0], s[1], s[2], rl)))
            elif rel < WRECK_PASS + CARD:
                show_card = (rel - WRECK_PASS, P["lred"], label + " DOWN", P["lred"],
                             "UP " + _uptime(up), P["white"])
            else:
                passed += 1
        elif kind == "sign":
            air_f, hum, water_f = data
            if rel < SIGN_PASS:
                d = _approach_d(rel / SIGN_PASS, 1.15)
                s = to_screen(d, 1.1, 0)
                if s:
                    sprites.append((d, lambda s=s: draw_sign(*s)))
            elif rel < SIGN_PASS + CARD:
                line1 = ("WATER %.1fF" % water_f, _water_pen(water_f)) if water_f is not None else ("WATER --", P["lgray"])
                if air_f is None:
                    line2 = ("AIR --", P["lgray"])
                else:
                    line2 = ("AIR %dF %s" % (round(air_f), ("%d%%" % hum) if hum is not None else ""), _temp_pen(air_f))
                show_card = (rel - SIGN_PASS, P["lcyan"], line1[0], line1[1], line2[0], line2[1])
        elif kind == "finish":
            f = min(1.0, rel / 2000)
            finish_d = _approach_d(f, 1.1)

    if show_card:
        card(*show_card)
        return

    race["pos"] += speed * dt * 0.012  # 12 world units a second
    curve = _curve_at(t) * speed
    # the road straightens while two bikes are side by side, so they stay put on screen
    fighting = any(0 <= t - s - APPROACH < FIGHT + KO for s, k, _ in race["events"] if k == "rival")
    if fighting:
        curve *= 0.2
    gfx.set_pen(P["black"])
    gfx.clear()
    draw_road(race["pos"], curve, finish_d)
    if speed > 0 and not fighting:
        _trees(race["pos"], curve)
    sprites.sort(key=lambda o: -o[0])
    for _, fn in sprites:
        fn()
    lean = -1 if curve > 0.35 else (1 if curve < -0.35 else 0)
    draw_biker(CX, H - 1, 1.0, P["lblue"], P["white"], lean=lean, punch=punch)

    if t < 3000:
        n = 3 - t // 800
        big(str(n) if n > 0 else "GO!", P["white"] if n > 0 else P["lgreen"], y=0)
        return
    if tag:
        gfx.set_pen(P["black"])
        gfx.rectangle(0, 0, tiny_w(tag[0]) + 2, 6)
        tiny(tag[0], 1, 0, tag[1])
    place = _ordinal(len(hosts) + 1 - passed)
    gfx.set_pen(P["black"])
    gfx.rectangle(W - tiny_w(place) - 2, 0, tiny_w(place) + 2, 6)
    tiny(place, W - tiny_w(place) - 1, 0, P["white"])


def results(t, info):
    """Results cards ranked by uptime, then the prize. True when done."""
    ranked = sorted(info["hosts"], key=lambda h: -1 if h[3] is None else h[3], reverse=True)
    cards = [(P["white"], "FINISH!", P["white"], "RESULTS", P["yellow"])]
    for i, h in enumerate(ranked):
        cards.append((P[h[1]], "%s %s" % (_ordinal(i + 1), h[0]), P[h[1]], "UP " + _uptime(h[3]), P["white"]))
    cards.append((P["yellow"], "YOU WIN", P["white"], "$%d" % (1000 * sum(1 for h in info["hosts"] if h[1] == "up")),
                  P["yellow"]))
    each = 1500
    i = t // each
    if i >= len(cards):
        return True
    card(t - i * each, *cards[i])
    return False
