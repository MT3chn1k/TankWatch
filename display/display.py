#!/usr/bin/env python3
"""TankWatch display: shows collector health and the latest readings on a small LED panel.

Panels:
  hatmini  Pimoroni Unicorn HAT Mini (17x7) on this Raspberry Pi
  web      the same picture in a web browser, http://<this machine>:8090 (for testing, or a screen with no HAT)

Layout (17x7): the two right-hand columns are one status light per collector, top to bottom (up to 7):
green = reporting, amber = reporting but undervolted, throttled or hot, red = silent for 90 s,
grey = unknown (the hub itself isn't answering, so the ticker shows HUB?).
The rest is a scrolling ticker of the latest readings, led by a red "<NAME> DOWN" for any silent collector.
Readings older than 15 minutes scroll in grey.

Settings come from environment variables:
  TANKWATCH_JOIN     the hub's DISPLAY join code (read-only); the hub is found again if its address changes
  PANEL              hatmini or web (default: hatmini if the HAT's library is installed, else web)
  BRIGHTNESS         0.0-1.0 for the HAT (default 0.15; it is very bright)
  WEB_PORT           port for the web panel (default 8090)
"""
import csv, io, logging, os, sys, time, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "node"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discovery                                                          # noqa: E402
from font3x5 import FONT                                                  # noqa: E402
from webpanel import WebPanel                                             # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s display: %(message)s")
log = logging.getLogger()

W, H = 17, 7
SILENT_S = 90
HOT_C = 77
STALE_S = 15 * 60
POLL_S = 20
SCROLL_S = 0.09

GREEN, AMBER, RED, GREY = (0, 170, 40), (230, 140, 0), (210, 0, 0), (70, 70, 70)
WATER, AIR, HUMID, PCT, WHITE = (0, 170, 220), (220, 220, 220), (60, 110, 255), (220, 190, 0), (200, 200, 200)


# ---------------------------------------------------------------------------------------------- hub
class Hub:
    def __init__(self, code):
        j = discovery.decode_join(code)
        if j["role"] != "display":
            raise SystemExit("that's the collector join code; a display needs the DISPLAY join code (read-only)")
        self.id, self.url, self.org, self.bucket, self.token = j["id"], j["url"], j["org"], j["bucket"], j["token"]
        self.failing_since = None

    def query(self, flux):
        req = urllib.request.Request("%s/api/v2/query?org=%s" % (self.url, self.org), data=flux.encode(), method="POST",
                                     headers={"Authorization": "Token " + self.token, "Content-Type": "application/vnd.flux",
                                              "Accept": "application/csv"})
        try:
            body = urllib.request.urlopen(req, timeout=8).read().decode()
            self.failing_since = None
        except Exception:
            self.failing_since = self.failing_since or time.time()
            if time.time() - self.failing_since > 180:          # the hub may have moved: look for it
                found = discovery.find_hubs(hub_id=self.id, hints=[discovery.host_of(self.url)])
                if found and found[0]["url"] != self.url:
                    log.warning("hub moved: %s -> %s", self.url, found[0]["url"])
                    self.url = found[0]["url"]
                self.failing_since = time.time()
            raise
        rows, head = [], None
        for rec in csv.reader(io.StringIO(body)):
            if len(rec) < 3:
                continue
            if rec[1] == "result":
                head = rec
            elif head:
                rows.append(dict(zip(head, rec)))
        return rows

    def status(self):
        """[(node, "up"|"warn"|"down")] in name order."""
        b = self.bucket
        ages = self.query('from(bucket:"%s") |> range(start:-24h) |> filter(fn:(r)=> r._measurement=="node_health" and r._field=="load1") '
                          '|> last() |> map(fn:(r)=>({node:r.node, age:(int(v:now()) - int(v:r._time)) / 1000000000})) '
                          '|> group() |> keep(columns:["node","age"])' % b)
        flags = self.query('from(bucket:"%s") |> range(start:-15m) |> filter(fn:(r)=> r._measurement=="node_health" and '
                           '(r._field=="undervolt_now" or r._field=="throttled_now" or r._field=="temp_c")) |> last() '
                           '|> map(fn:(r)=>({node:r.node, f:r._field, v:float(v:r._value)})) |> group() |> keep(columns:["node","f","v"])' % b)
        f = {}
        for r in flags:
            f.setdefault(r["node"], {})[r["f"]] = float(r["v"])
        out = []
        for r in sorted(ages, key=lambda r: r["node"]):
            n, h = r["node"], f.get(r["node"], {})
            if int(r["age"]) > SILENT_S:
                out.append((n, "down"))
            elif h.get("undervolt_now") or h.get("throttled_now") or h.get("temp_c", 0) > HOT_C:
                out.append((n, "warn"))
            else:
                out.append((n, "up"))
        return out

    def readings(self):
        """[(text, colour)] for the ticker: latest value per location and kind."""
        rows = self.query('from(bucket:"%s") |> range(start:-6h) |> filter(fn:(r)=> r._measurement!="node_health" and '
                          '(r._field=="temp_f" or r._field=="humidity" or r._field=~/_pct$/)) |> last() '
                          '|> map(fn:(r)=>({loc:r.location, m:r._measurement, f:r._field, v:float(v:r._value), '
                          'age:(int(v:now()) - int(v:r._time)) / 1000000000})) |> group() |> keep(columns:["loc","m","f","v","age"])'
                          % self.bucket)
        out = []
        for r in sorted(rows, key=lambda r: (r["loc"], r["m"], r["f"])):
            v, stale = float(r["v"]), int(r["age"]) > STALE_S
            if r["f"] == "temp_f":
                text, colour = "%s %.1fF" % (r["loc"], v), WATER if r["m"] == "water" else AIR
            elif r["f"] == "humidity":
                text, colour = "%s %d%%RH" % (r["loc"], round(v)), HUMID
            else:
                text, colour = "%s %s %d%%" % (r["loc"], r["f"][:-4], round(v)), PCT
            out.append((text.upper(), GREY if stale else colour))
        return out


# ---------------------------------------------------------------------------------------------- panels
class HatMiniPanel:
    def __init__(self, brightness):
        from unicornhatmini import UnicornHATMini
        self.u = UnicornHATMini()
        self.u.set_brightness(brightness)
        self.u.set_rotation(0)

    def show(self, fb):
        for i, (r, g, b) in enumerate(fb):
            self.u.set_pixel(i % W, i // W, r, g, b)
        self.u.show()


# ---------------------------------------------------------------------------------------------- drawing
def text_columns(segments):
    """[(text, colour)] -> list of 5-pixel columns, each a list of colours (None = off), with gaps."""
    cols = []
    for text, colour in segments:
        for ch in text:
            glyph = FONT.get(ch, FONT["?"])
            for x in range(len(glyph[0])):
                cols.append([colour if glyph[y][x] == "#" else None for y in range(5)])
            cols.append([None] * 5)
        cols += [[None] * 5] * 4
    return cols


def frame(status, cols, offset):
    fb = [(0, 0, 0)] * (W * H)
    for x in range(W - 2):                                   # ticker, rows 1-5
        c = cols[(offset + x) % len(cols)] if cols else [None] * 5
        for y in range(5):
            if c[y]:
                fb[(y + 1) * W + x] = c[y]
    for row, (node, state) in enumerate(status[:H]):       # status lights: right two columns
        colour = {"up": GREEN, "warn": AMBER, "down": RED}.get(state, GREY)
        fb[row * W + W - 2] = fb[row * W + W - 1] = colour
    return fb


def main():
    code = os.environ.get("TANKWATCH_JOIN")
    if not code:
        raise SystemExit("set TANKWATCH_JOIN to the hub's DISPLAY join code (on the hub: ./setup.sh codes)")
    hub = Hub(code)
    kind = os.environ.get("PANEL")
    if not kind:
        try:
            import unicornhatmini  # noqa: F401
            kind = "hatmini"
        except ImportError:
            kind = "web"
    panel = HatMiniPanel(float(os.environ.get("BRIGHTNESS", "0.15"))) if kind == "hatmini" else WebPanel(W, H, int(os.environ.get("WEB_PORT", "8090")), "TankWatch display (virtual Unicorn HAT Mini)")
    log.info("display on %s panel, hub %s at %s", kind, hub.id, hub.url)

    status, cols, offset, last_poll = [], text_columns([("HELLO", WHITE)]), 0, 0.0
    while True:
        if time.time() - last_poll >= POLL_S:
            last_poll = time.time()
            try:
                status = hub.status()
                down = [(n.upper() + " DOWN", RED) for n, s in status if s == "down"]
                cols = text_columns(down + (hub.readings() or [("NO READINGS YET", GREY)]))
            except Exception as e:
                log.warning("hub query failed: %s", e)
                cols = text_columns([("HUB?", RED)])
                status = [(n, "unknown") for n, _ in status]   # the hub is down, not necessarily them
        panel.show(frame(status, cols, offset))
        offset += 1
        time.sleep(SCROLL_S)


if __name__ == "__main__":
    main()
