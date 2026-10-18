"""TankWatch status sign on the Pimoroni Galactic Unicorn (Pico 2 W).

Shows one location's air temperature (F) and humidity and another's water temperature from the
TankWatch hub, plus the health of up to four collectors (the blocks on the right edge, top to
bottom, in the order listed in config.json). Health comes from the node_health reports each
collector sends the hub: green = reporting, amber = reporting but undervolted, throttled or hot,
red = silent for 90 s. If the hub can't be reached, the hub's block goes red and the sign checks
the other collectors itself (does port 22 answer?). Data older than 15 minutes is drawn grey with
its age.

Styles (volume up / down step through them; the choice is kept in style.txt across reboots):
  1 STD   standard readout: A air temperature (press again for water), B humidity, otherwise
          auto-rotate AIR, WATER, humidity, 24-hour uptime
  2 RASH  Road Rash race reporting uptime, CPU temps, water and air (roadrash.py); C jumps here
  3 DEMO  1990s demoscene loop (demo.py); D jumps here
  4 SYNTH sunset drive past the monitored items; the lake is the tank (synthwave.py)
Pressing C or D again goes back to STD.
Brightness up/down as usual; Zzz turns the display off and on.
Which hub, collectors and locations to show live in config.json (see config.example.json).
Wi-Fi name/password and the InfluxDB read-only token live in secrets.py.
"""
import json
import math
import time
import machine
import network
import rp2
import socket
import ntptime
import urequests
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
import secrets

with open("config.json") as _f:
    CFG = json.load(_f)
# Collectors, top to bottom; the edge has room for four 3x2 blocks
NODES = CFG["nodes"][:4]
NAMES = [n["name"] for n in NODES]
HUB = ([n["name"] for n in NODES if n.get("hub")] or [None])[0]
BUCKET = CFG.get("bucket", "sensors")
INFLUX = "%s/api/v2/query?org=%s" % (CFG["hub_url"].rstrip("/"), CFG.get("org", "tankwatch"))


def _readings_filter():
    """Flux filter for the air location's temperature and humidity and the water location's temperature."""
    parts = []
    if CFG.get("air_location"):
        parts.append('(r._measurement=="air" and r.location=="%s" and (r._field=="temp_f" or r._field=="humidity"))'
                     % CFG["air_location"])
    if CFG.get("water_location"):
        parts.append('(r._measurement=="water" and r.location=="%s" and r._field=="temp_f")' % CFG["water_location"])
    return "|> filter(fn:(r)=> %s) " % (" or ".join(parts) or "false")


FLUX = ('from(bucket:"%s") |> range(start:-24h) ' % BUCKET + _readings_filter()
        + '|> last() |> keep(columns:["_time","_measurement","_field","_value"])')
HEALTH_FLUX = ('from(bucket:"%s") |> range(start:-15m) ' % BUCKET
               + '|> filter(fn:(r)=> r._measurement=="node_health" and (r._field=="load1" or r._field=="undervolt_now" or r._field=="throttled_now" or r._field=="temp_c")) '
               '|> last() |> map(fn:(r)=>({node:r.node, f:r._field, v:float(v:r._value), age:(int(v:now()) - int(v:r._time)) / 1000000000})) '
               '|> group() |> keep(columns:["node","f","v","age"])')
# share of 2-minute windows with a health report, counted from each collector's first report in the last 24 h
UPTIME_FLUX = ('from(bucket:"%s") |> range(start:-24h, stop:-1m) ' % BUCKET
               + '|> filter(fn:(r)=> r._measurement=="node_health" and r._field=="load1") '
               '|> aggregateWindow(every:2m, fn:count, createEmpty:true) '
               '|> map(fn:(r)=>({r with up: if r._value > 0 then 1.0 else 0.0, started: if r._value > 0 then 1 else 0})) '
               '|> cumulativeSum(columns:["started"]) |> filter(fn:(r)=> r.started > 0) '
               '|> mean(column:"up") |> group() |> keep(columns:["node","up"])')
# the same over the last hour; gold needs this at 100%
UPTIME_HOUR_FLUX = UPTIME_FLUX.replace("start:-24h", "start:-1h")
GOLD_DAY = 0.998        # gold: at least 99.8% over 24 h (at most one missed 2-minute check) ...
GOLD_HOUR = 0.9995      # ... and 100% over the last hour
SILENT_S = 90      # no health report for this long = down
HOT_C = CFG.get("hot_cpu_c", 77)   # 77 C is about 170 F
AIR_RANGE = CFG.get("air_range_f", [68, 80])
WATER_RANGE = CFG.get("water_range_f", [74, 82])
POLL_DATA_S = 60
POLL_HOSTS_S = 30
POLL_UPTIME_S = 10 * 60
# last hour of readings in 74 s steps: one step per display column left of the status blocks
TREND_COLS = 49
TREND_FLUX = ('from(bucket:"%s") |> range(start:-1h) ' % BUCKET + _readings_filter()
              + '|> aggregateWindow(every:74s, fn:mean, createEmpty:true) |> keep(columns:["_measurement","_field","_value"])')
TREND_MIN_SPAN = {"temp_f": 2.0, "humidity": 5.0, "water": 1.0}  # keeps sensor noise from looking like big swings
POLL_TREND_S = 2 * 60
STALE_S = 15 * 60
ROTATE_S = 6


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    try:
        with open("log.txt", "a") as f:
            f.write("%d %s\n" % (time.ticks_ms() // 1000, msg))
    except OSError:
        pass


try:
    import os
    if os.stat("log.txt")[6] > 8000:
        os.remove("log.txt")
except OSError:
    pass
log("boot, cpu", machine.freq())

wlan = network.WLAN(network.STA_IF)


def wifi_start():
    rp2.country(CFG.get("wifi_country", "US"))
    wlan.active(True)
    wlan.config(pm=0xa11140)  # no power-save, keeps the link responsive
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)


# Start Wi-Fi before the LED driver claims its hardware (they clash on the Pico 2 W otherwise)
try:
    wifi_start()
    log("wifi started")
except OSError as e:
    log("wifi start failed", e)

gu = GalacticUnicorn()
gfx = PicoGraphics(DISPLAY)
W, H = GalacticUnicorn.WIDTH, GalacticUnicorn.HEIGHT

BLACK = gfx.create_pen(0, 0, 0)
GREY = gfx.create_pen(90, 90, 90)
WHITE = gfx.create_pen(200, 200, 200)
GREEN = gfx.create_pen(0, 170, 40)
RED = gfx.create_pen(200, 0, 0)
BLUE = gfx.create_pen(40, 110, 255)
ORANGE = gfx.create_pen(255, 110, 0)
CYAN = gfx.create_pen(0, 160, 200)
AMBER = gfx.create_pen(230, 150, 0)
GOLD = gfx.create_pen(255, 215, 0)       # outline for a full 24 hours up; yellower than AMBER (a warning)
TREND_FILL = gfx.create_pen(45, 25, 0)   # faded amber behind the readings
TREND_TOP = gfx.create_pen(95, 55, 0)

# hosts: None = not checked yet, else "up", "warn" or "down"; uptime: fraction 0-1
state = {"temp_f": None, "hum": None, "t": None, "hosts": {n: None for n in NAMES}, "detail": {},
         "uptime": {}, "uptime_hour": {}, "trend": {}, "err": None, "clock_ok": False}

wifi_fails = 0


def wifi_up():
    global wifi_fails
    if wlan.isconnected():
        wifi_fails = 0
        return True
    try:
        if wlan.status() not in (network.STAT_CONNECTING,):
            wifi_start()
    except OSError as e:
        wifi_fails += 1
        log("wifi error", e, "fail", wifi_fails)
        show_message("WIFI ERR", RED)
        if wifi_fails >= 3:
            log("resetting board")
            time.sleep(2)
            machine.reset()
        return False
    for _ in range(40):
        if wlan.isconnected():
            log("wifi ok", wlan.ifconfig()[0])
            wifi_fails = 0
            return True
        show_message("WIFI...", GREY)
        time.sleep(0.5)
    return False


def parse_time(s):
    # 2026-10-16T03:27:20.254313637Z -> seconds since the board's epoch (UTC)
    d, t = s.rstrip("Z").split("T")
    y, mo, dd = (int(x) for x in d.split("-"))
    hh, mi, ss = t.split(":")
    return time.mktime((y, mo, dd, int(hh), int(mi), int(float(ss)), 0, 0))


def influx(flux):
    """Run a Flux query on the hub and return its rows as dicts; raises on any failure."""
    r = urequests.post(INFLUX, data=flux, headers={
        "Authorization": "Token " + secrets.INFLUX_TOKEN,
        "Content-Type": "application/vnd.flux", "Accept": "application/csv"}, timeout=5)
    try:
        if r.status_code != 200:
            raise OSError("DB %d" % r.status_code)
        body = r.text
    finally:
        r.close()
    rows, head = [], None
    for line in body.split("\n"):
        cols = line.strip().split(",")
        if len(cols) < 3:
            continue
        if cols[1] == "result":
            head = cols
        elif head:
            rows.append(dict(zip(head, cols)))
    return rows


def poll_data():
    if not state["clock_ok"]:
        ntptime.timeout = 3
        for host in ("pool.ntp.org", "time.google.com", "time.cloudflare.com"):
            try:
                ntptime.host = host
                ntptime.settime()
                state["clock_ok"] = True
                log("ntp ok via", host)
                break
            except Exception:
                pass
    try:
        got = {}
        for row in influx(FLUX):
            key = "water" if row["_measurement"] == "water" else row["_field"]
            got[key] = (float(row["_value"]), row["_time"])
        state["temp_f"] = got["temp_f"][0] if "temp_f" in got else None
        state["hum"] = got["humidity"][0] if "humidity" in got else None
        state["t"] = parse_time(got["temp_f"][1]) if "temp_f" in got else None
        state["water_f"] = got["water"][0] if "water" in got else None
        state["water_t"] = parse_time(got["water"][1]) if "water" in got else None
        if state["err"] is not None or not state.get("logged_data"):
            log("data", state["temp_f"], state["hum"], state["water_f"])  # first reading and recoveries only, spares the flash
            state["logged_data"] = True
        state["err"] = None
    except Exception as e:
        log("influx error", e)
        state["err"] = "DB?"


def ssh_answers(ip):
    s = socket.socket()
    s.settimeout(3)  # a Pi on Wi-Fi can take over a second to answer the first time
    try:
        s.connect(socket.getaddrinfo(ip, 22)[0][-1])
        return True
    except Exception:
        return False
    finally:
        s.close()


def set_host(name, status):
    old = state["hosts"][name]
    if status != old and (old is not None or status != "up"):
        log("host", name, status)
    state["hosts"][name] = status


def poll_hosts():
    try:
        rows = influx(HEALTH_FLUX)
    except Exception as e:
        # hub unreachable: mark it down and check the other collectors directly
        if HUB is None or state["hosts"][HUB] != "down":
            log("health query failed, direct checks:", e)
        for n in NODES:
            if n["name"] == HUB:
                set_host(n["name"], "down")
            elif n.get("address"):
                set_host(n["name"], "up" if ssh_answers(n["address"]) or ssh_answers(n["address"]) else "down")
            else:
                set_host(n["name"], None)  # no address to check: grey, unknown
        return
    seen = {}
    for row in rows:
        h = seen.setdefault(row["node"], {})
        h[row["f"]] = float(row["v"])
        h["age"] = min(h.get("age", 10 ** 9), int(row["age"]))  # newest field wins; load1 comes from every collector
    for name in NAMES:
        h = seen.get(name)
        if h and "temp_c" in h:
            why = "LOWV" if h.get("undervolt_now") else "THRT" if h.get("throttled_now") else "HOT" if h["temp_c"] > HOT_C else None
            state["detail"][name] = (round(h["temp_c"] * 9 / 5 + 32), why)
        else:
            state["detail"][name] = (None, None)
        if not h or h["age"] > SILENT_S:
            set_host(name, "down")
        elif h.get("undervolt_now") or h.get("throttled_now") or h.get("temp_c", 0) > HOT_C:
            set_host(name, "warn")
        else:
            set_host(name, "up")


def poll_uptime_hour():
    try:
        state["uptime_hour"] = {row["node"]: float(row["up"]) for row in influx(UPTIME_HOUR_FLUX)}
    except Exception as e:
        log("hour uptime query failed", e)


def poll_uptime():
    try:
        state["uptime"] = {row["node"]: float(row["up"]) for row in influx(UPTIME_FLUX)}
    except Exception as e:
        log("uptime query failed", e)


def fill_short_gaps(vals, longest=2):
    # collectors log about once a minute, so some 74 s steps are empty; bridge those,
    # but leave longer gaps (a real sensor outage) visible
    out = list(vals)
    i = 0
    while i < len(out):
        if out[i] is None:
            j = i
            while j < len(out) and out[j] is None:
                j += 1
            if j - i <= longest and i > 0 and j < len(out):
                for k in range(i, j):
                    out[k] = out[i - 1] + (out[j] - out[i - 1]) * (k - i + 1) / (j - i + 1)
            i = j
        else:
            i += 1
    return out


def poll_trend():
    try:
        series = {"temp_f": [], "humidity": [], "water": []}
        for row in influx(TREND_FLUX):
            key = "water" if row["_measurement"] == "water" else row["_field"]
            if key in series:
                series[key].append(float(row["_value"]) if row["_value"] else None)
        state["trend"] = {f: fill_short_gaps(v[-TREND_COLS:]) for f, v in series.items()}
    except Exception as e:
        log("trend query failed", e)


def draw_trend(field):
    """Faded amber area graph of the last hour, newest on the right, scaled to the hour's range."""
    vals = state["trend"].get(field)
    if not vals:
        return
    got = [v for v in vals if v is not None]
    if not got:
        return
    lo, hi = min(got), max(got)
    span = max(hi - lo, TREND_MIN_SPAN[field])
    lo = (lo + hi - span) / 2
    x0 = TREND_COLS - len(vals)
    for i, v in enumerate(vals):
        if v is None:
            continue
        h = 1 + int((v - lo) / span * (H - 2) + 0.5)  # 1..H-1 pixels tall
        gfx.set_pen(TREND_FILL)
        gfx.rectangle(x0 + i, H - h, 1, h)
        gfx.set_pen(TREND_TOP)
        gfx.pixel(x0 + i, H - h)


def age_s(key="t"):
    if state.get(key) is None or not state["clock_ok"]:
        return None
    return time.time() - state[key]


def stale(key="t"):
    """key "t" = the air reading, "water_t" = the water reading."""
    # without a clock we can't judge age, so show the reading as current
    if not state["clock_ok"]:
        return False
    a = age_s(key)
    return a is None or a > STALE_S


def age_text(key="t"):
    a = age_s(key)
    if a is None:
        return "OLD"
    m = int(a // 60)
    return "%dm" % m if m < 60 else "%dh" % (m // 60)


def temp_pen(f):
    if f < AIR_RANGE[0]:
        return BLUE
    if f > AIR_RANGE[1]:
        return ORANGE
    return GREEN


def water_pen(f):
    if f < WATER_RANGE[0]:
        return BLUE
    if f > WATER_RANGE[1]:
        return ORANGE
    return GREEN


def host_pen(name):
    return {"up": GREEN, "warn": AMBER, "down": RED}.get(state["hosts"][name], GREY)


def uptime_text(name):
    u = state["uptime"].get(name)
    if u is None:
        return "--"
    if u >= 0.9995:
        # 100% means gold, so never show it without the gold (same test as draw_names)
        return "100%" if full_day(name) and state["hosts"][name] != "down" else "99%"
    # whole numbers from 10% up, rounded down so 99.7% reads 99% (100% means a full day)
    return "%d%%" % int(u * 100) if u >= 0.1 else "%.1f%%" % (u * 100)


def draw_hosts():
    # up to four 3x2 blocks on the right edge, in config.json order
    for i, name in enumerate(NAMES):
        gfx.set_pen(host_pen(name))
        gfx.rectangle(W - 3, i * 3, 3, 2)


def centered(text, pen, font="bitmap8", y=2, area=W - 4):
    gfx.set_font(font)
    gfx.set_pen(pen)
    w = gfx.measure_text(text, 1)
    gfx.text(text, max(0, (area - w) // 2), y, -1, 1)


def show_message(text, pen):
    gfx.set_pen(BLACK)
    gfx.clear()
    centered(text, pen, area=W)
    gu.update(gfx)


# 3x5 letters for the AIR / WATER tags on the temperature screens
TAG_FONT = {"A": "010101111101101", "I": "111010010010111", "R": "110101110101101",
            "W": "101101111111101", "T": "111010010010010", "E": "111100110100111"}


def draw_tag(text, pen):
    gfx.set_pen(pen)
    x = 0
    for ch in text:
        bits = TAG_FONT[ch]
        for k in range(15):
            if bits[k] == "1":
                gfx.pixel(x + k % 3, 3 + k // 3)
        x += 4
    return x  # first free column


def tagged_value(tag, text, pen):
    """Tag on the left, value centred in the space left of the host blocks; drops the decimal if it won't fit."""
    x0 = draw_tag(tag, GREY)
    gfx.set_font("bitmap8")
    area = W - 4 - x0
    if gfx.measure_text(text, 1) > area and "." in text:
        text = text.split(".")[0] + text[-1]
    w = gfx.measure_text(text, 1)
    gfx.set_pen(pen)
    gfx.text(text, x0 + max(0, (area - w) // 2), 2, -1, 1)


def draw_temp(blink):
    f = state["temp_f"]
    draw_trend("temp_f")
    if f is None:
        centered(state["err"] or "NO DATA", RED)
    elif stale():
        tagged_value("AIR", ("%.1fF" % f) if blink else age_text(), GREY)
    else:
        tagged_value("AIR", "%.1fF" % f, temp_pen(f))


def draw_water(blink):
    f = state.get("water_f")
    draw_trend("water")
    if f is None:
        tagged_value("WATER", state["err"] or "--", RED)
    elif stale("water_t"):
        tagged_value("WATER", ("%.1fF" % f) if blink else age_text("water_t"), GREY)
    else:
        tagged_value("WATER", "%.1fF" % f, water_pen(f))


def draw_hum(blink):
    h = state["hum"]
    draw_trend("humidity")
    if h is None:
        centered(state["err"] or "NO DATA", RED)
    elif stale():
        centered(("%d%%RH" % h) if blink else age_text(), GREY)
    else:
        centered("%d%%RH" % h, CYAN)


scroll_x = W


# 15x9 fish facing right; the collector's number is cut out of its body and the eye is a dark pixel
FISH = ("#.....#####....",
        "##..#########..",
        "##############.",
        ".#############.",
        "..#############",
        ".#############.",
        "##############.",
        "##..#########..",
        "#.....#####....")
FISH_EYE = (12, 3)
FISH_DIGIT_AT = (6, 2)
DIGITS = {"1": (".#.", "##.", ".#.", ".#.", "###"),
          "2": ("##.", "..#", ".#.", "#..", "###"),
          "3": ("##.", "..#", ".#.", "..#", "##."),
          "4": ("#.#", "#.#", "###", "..#", "..#")}


# 9x8 heart for the hub. While the hub is reporting it glows: its brightness swells and fades
# smoothly, once every 2.4 s. Down or not checked yet, it stays steady.
HEART = (".##...##.",
         "#########",
         "#########",
         "#########",
         ".#######.",
         "..#####..",
         "...###...",
         "....#....")
GLOW_MS = 2400
GLOW_RGB = {"up": (0, 170, 40), "warn": (230, 150, 0)}   # the GREEN and AMBER pens


def heart_pen(status, pen):
    rgb = GLOW_RGB.get(status)
    if rgb is None:
        return pen
    f = 0.675 + 0.325 * math.cos(2 * math.pi * (time.ticks_ms() % GLOW_MS) / GLOW_MS)   # 35% .. 100%
    return gfx.create_pen(int(rgb[0] * f), int(rgb[1] * f), int(rgb[2] * f))


def _outline(art):
    """The pixels just outside an icon's shape (all eight directions), as (dx, dy) offsets."""
    h, w = len(art), len(art[0])
    on = lambda c, r: 0 <= r < h and 0 <= c < w and art[r][c] == "#"
    return tuple((c, r) for r in range(-1, h + 1) for c in range(-1, w + 1)
                 if not on(c, r) and any(on(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)))


OUTLINES = {}


def draw_art(x, y, art, pen, gold=False):
    if gold:
        if art not in OUTLINES:
            OUTLINES[art] = _outline(art)
        gfx.set_pen(GOLD)
        for dx, dy in OUTLINES[art]:
            gfx.pixel(x + dx, y + dy)
    gfx.set_pen(pen)
    for r, row in enumerate(art):
        for c, ch in enumerate(row):
            if ch == "#":
                gfx.pixel(x + c, y + r)


def full_day(name):
    """Gold: at least 99.8% over the last 24 hours and 100% over the last hour (2-minute windows)."""
    u, h = state["uptime"].get(name), state["uptime_hour"].get(name)
    return u is not None and h is not None and u >= GOLD_DAY and h >= GOLD_HOUR


def draw_fish(x, y, pen, digit, gold=False):
    draw_art(x, y, FISH, pen, gold)
    gfx.set_pen(BLACK)
    gfx.pixel(x + FISH_EYE[0], y + FISH_EYE[1])
    dx, dy = FISH_DIGIT_AT
    for r, row in enumerate(DIGITS.get(digit, ())):
        for c, ch in enumerate(row):
            if ch == "#":
                gfx.pixel(x + dx + c, y + dy + r)


def draw_names():
    """Scroll each collector's 24-hour uptime, coloured by health: "<fish 1> 99.7%  <heart> ...".
    A collector that was up the whole 24 hours gets a gold outline instead of "100%". True once it has scrolled past."""
    global scroll_x
    gfx.set_font("bitmap8")
    x = scroll_x
    for n in NODES:
        name = n["name"]
        pen = host_pen(name)
        gold = full_day(name) and state["hosts"][name] != "down"  # a dead collector loses its gold at once
        icon = n.get("icon")
        if icon in ("fish", "heart"):
            x += 1  # room for the outline
            if icon == "fish":
                draw_fish(x, 1, pen, n["label"][-1:], gold)
                x += len(FISH[0]) + 2
            else:
                draw_art(x, 2, HEART, heart_pen(state["hosts"][name], pen), gold)
                x += len(HEART[0]) + 2
            text = "" if gold else uptime_text(name)
        elif gold:
            # no icon: the label in a gold box
            text = n["label"]
            gfx.set_pen(GOLD)
            w = gfx.measure_text(text, 1)
            gfx.rectangle(x, 0, w + 3, 1)
            gfx.rectangle(x, H - 1, w + 3, 1)
            gfx.rectangle(x, 0, 1, H)
            gfx.rectangle(x + w + 2, 0, 1, H)
            gfx.set_pen(pen)
            gfx.text(text, x + 2, 2, -1, 1)
            x += w + 3 + 4
            text = ""
        else:
            text = "%s %s" % (n["label"], uptime_text(name))
        if text:
            gfx.set_pen(pen)
            gfx.text(text, x, 2, -1, 1)
            x += gfx.measure_text(text + "   ", 1)
        else:
            x += 3
    scroll_x -= 1
    if x < 0:
        scroll_x = W
        return True
    return False



# Display styles, stepped through with the volume buttons (C and D jump to Road Rash and the demo).
# (key, short name shown when switching, module or None for the standard readout). Room for ten.
STYLES = [("std", "STD", None), ("rash", "RASH", "roadrash"), ("demo", "DEMO", "demo"), ("synth", "SYNTH", "synthwave")]
SHOW_MODULES = ("roadrash", "demo", "synthwave")
STYLE_FILE = "style.txt"


def saved_style():
    try:
        with open(STYLE_FILE) as f:
            key = f.read().strip()
        return key if any(k == key for k, _, _ in STYLES) else "std"
    except OSError:
        return "std"


def save_style(key):
    try:
        with open(STYLE_FILE, "w") as f:
            f.write(key)
    except OSError:
        pass


def load_show(modname):
    """Import one show module, dropping the others first so only one sits in RAM."""
    import sys, gc
    for m in SHOW_MODULES:
        if m in sys.modules and m != modname and not (modname == "roadrash" and m == "demo"):
            del sys.modules[m]
    gc.collect()
    return __import__(modname)


def tank_reading():
    """(air F, humidity %, water F) for the shows; a stale reading is None."""
    air_ok = not stale()
    return (state["temp_f"] if air_ok else None, state["hum"] if air_ok else None,
            None if stale("water_t") else state.get("water_f"))


def show_info():
    return {"hosts": demo_hosts(), "tank": tank_reading(), "water_range": WATER_RANGE, "air_range": AIR_RANGE}


def demo_hosts(fill=0):
    """(label, status, CPU F, uptime, warning) per collector. fill=4 repeats the list to four entries,
    for demo scenes built around exactly four (the fire and the donut)."""
    out = []
    for n in NODES:
        name = n["name"]
        status = state["hosts"][name]
        temp_f, why = state["detail"].get(name, (None, None))
        out.append((n["label"], status, temp_f if status != "down" else None, state["uptime"].get(name), why))
    while out and len(out) < fill:
        out.append(out[len(out) % len(NODES)])
    return out


def main():
    global scroll_x
    brightness = 0.5
    mode = "auto"
    screen = 0
    asleep = False
    was_sleep = False
    last_rotate = last_data = last_hosts = last_uptime = last_trend = -1000
    scrolled = False
    was_a = was_c = was_d = was_vu = was_vd = False
    show = None           # module of the running show; None = standard readout
    demo_ms = 0           # the shows' own clock; survives ticks_ms() wrapping
    demo_tick = time.ticks_ms()
    style = "std"
    label_until = None    # ticks_ms until which the style name stays on screen, None when not showing

    def select(key):
        nonlocal show, mode, style, demo_tick, last_rotate, label_until
        name, modname = [(n, m) for k, n, m in STYLES if k == key][0]
        show_message("%d %s" % ([k for k, _, _ in STYLES].index(key) + 1, name), WHITE)
        try:
            show = load_show(modname) if modname else None
        except Exception as e:
            log("style", key, "failed to load:", e)
            show, key, modname = None, "std", None
        if show and hasattr(show, "restart"):
            show.restart()
        mode = key if show else "auto"
        last_rotate = now
        style = key
        demo_tick = time.ticks_ms()
        label_until = time.ticks_add(time.ticks_ms(), 900)
        save_style(key)
        log("style", key)

    gu.set_brightness(brightness)
    show_message("HELLO", WHITE)
    log("display running")
    now = time.ticks_ms() // 1000
    boot_style = saved_style()
    if boot_style != "std":
        select(boot_style)

    while True:
        now = time.ticks_ms() // 1000

        # buttons
        a_pressed = gu.is_pressed(GalacticUnicorn.SWITCH_A)
        if a_pressed and not was_a:  # A: air temperature, press again for water
            mode, screen = "fixed", (1 if mode == "fixed" and screen == 0 else 0)
        elif gu.is_pressed(GalacticUnicorn.SWITCH_B):
            mode, screen = "fixed", 2
        was_a = a_pressed
        if mode == "fixed" and show:  # A / B leave a running show for the standard readout
            select("std")
            mode = "fixed"
        c_pressed = gu.is_pressed(GalacticUnicorn.SWITCH_C)
        d_pressed = gu.is_pressed(GalacticUnicorn.SWITCH_D)
        vu = gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_UP)
        vd = gu.is_pressed(GalacticUnicorn.SWITCH_VOLUME_DOWN)
        for key, pressed, was in (("rash", c_pressed, was_c), ("demo", d_pressed, was_d)):
            if pressed and not was:
                select("std" if style == key else key)
        if (vu and not was_vu) or (vd and not was_vd):
            keys = [k for k, _, _ in STYLES]
            select(keys[(keys.index(style) + (1 if vu else -1)) % len(keys)])
        was_c, was_d, was_vu, was_vd = c_pressed, d_pressed, vu, vd
        if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_UP):
            brightness = min(1.0, brightness + 0.01)
        if gu.is_pressed(GalacticUnicorn.SWITCH_BRIGHTNESS_DOWN):
            brightness = max(0.05, brightness - 0.01)
        sleep_pressed = gu.is_pressed(GalacticUnicorn.SWITCH_SLEEP)
        if sleep_pressed and not was_sleep:
            asleep = not asleep
        was_sleep = sleep_pressed
        gu.set_brightness(0 if asleep else brightness)

        # network work (blocks the display for a moment)
        if now - last_data >= POLL_DATA_S or now - last_hosts >= POLL_HOSTS_S:
            if wifi_up():
                if now - last_data >= POLL_DATA_S:
                    poll_data()
                    last_data = now
                if now - last_hosts >= POLL_HOSTS_S:
                    poll_hosts()
                    last_hosts = now
                if now - last_uptime >= POLL_UPTIME_S:
                    poll_uptime()
                    last_uptime = now
                if now - last_trend >= POLL_TREND_S:
                    poll_trend()
                    poll_uptime_hour()
                    last_trend = now
            else:
                state["err"] = "WIFI?"
                last_data = last_hosts = now - POLL_HOSTS_S + 10  # retry in 10 s

        # the uptime screen stays until its text has scrolled past once
        if mode == "auto" and now - last_rotate >= ROTATE_S and (screen != 3 or scrolled):
            screen = (screen + 1) % 4
            last_rotate = now
            scroll_x = W
            scrolled = False

        if label_until is not None:  # style name still showing
            if time.ticks_diff(label_until, time.ticks_ms()) > 0:
                time.sleep_ms(20)
                continue
            label_until = None
        if show:
            tick = time.ticks_ms()
            demo_ms += time.ticks_diff(tick, demo_tick)
            demo_tick = tick
            try:
                if style == "demo":
                    show.frame(gfx, demo_ms, demo_hosts(fill=4), tank_reading())
                else:
                    show.frame(gfx, demo_ms, show_info())
            except Exception as e:  # a broken style must not freeze the display
                log("style", style, "crashed:", e)
                select("std")
                continue
            gu.update(gfx)
            spare = 20 - time.ticks_diff(time.ticks_ms(), tick)  # cap at 50 fps
            time.sleep_ms(spare if spare > 1 else 1)
            continue

        blink = (now // 2) % 2 == 0
        gfx.set_pen(BLACK)
        gfx.clear()
        if screen == 0:
            draw_temp(blink)
        elif screen == 1:
            draw_water(blink)
        elif screen == 2:
            draw_hum(blink)
        else:
            scrolled = draw_names() or scrolled
        if screen != 3:
            draw_hosts()
        gu.update(gfx)
        time.sleep(0.04)


main()
