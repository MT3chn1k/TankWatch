"""Run the sign's main.py on the PC against a real TankWatch hub, with the Pico hardware faked, and save
each screen as a contact sheet. Checks the config, the hub queries and the drawing without a board.

Usage: python sim_main.py CONFIG.json TOKEN out.png
  CONFIG.json  the sign's config (hub_url must be reachable from this PC)
  TOKEN        a read-only token (hub/.env INFLUX_READ_TOKEN)
"""
import json, os, sys, time, types, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sim_gfx import FakeGfx, sheet, W, H  # noqa: E402  (also installs a fake micropython module)

cfg_path, token, out = sys.argv[1], sys.argv[2], sys.argv[3]


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text

    def close(self):
        pass


def post(url, data=None, headers=None, timeout=5):
    req = urllib.request.Request(url, data=data.encode(), headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, r.read().decode())
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.read().decode())


class FakeWlan:
    def __init__(self, *a): pass
    def active(self, *a): pass
    def config(self, **k): pass
    def connect(self, *a): pass
    def isconnected(self): return True
    def status(self): return 3
    def ifconfig(self): return ("127.0.0.1",)


class FakeUnicorn:
    WIDTH, HEIGHT = W, H
    def set_brightness(self, b): pass
    def update(self, g): pass
    def is_pressed(self, k): return False


stub("machine", freq=lambda: 150000000, reset=lambda: None)
stub("network", WLAN=FakeWlan, STA_IF=0, STAT_CONNECTING=1)
stub("rp2", country=lambda c: None)
stub("ntptime", settime=lambda: None, timeout=3, host="")
stub("urequests", post=post)
stub("galactic", GalacticUnicorn=FakeUnicorn)
stub("picographics", PicoGraphics=lambda d: FakeGfx(), DISPLAY_GALACTIC_UNICORN=0)
stub("secrets", WIFI_SSID="", WIFI_PASSWORD="", INFLUX_TOKEN=token)

# MicroPython's time has ticks_* and sleep_ms; its mktime takes an 8-tuple and returns UTC seconds
time.ticks_ms = lambda: int(time.monotonic() * 1000)
time.ticks_diff = lambda a, b: a - b
time.ticks_add = lambda a, b: a + b
time.sleep_ms = lambda ms: None
_real_mktime = time.mktime
time.mktime = lambda t: int(__import__("calendar").timegm(tuple(t[:6]) + (0, 0, 0)))

# Load main.py without running its endless main() loop, reading config.json from cfg_path
src = open(os.path.join(HERE, "..", "main.py"), encoding="utf-8").read()
src = src.replace('open("config.json")', "open(%r)" % cfg_path)
src = src[:src.rstrip().rfind("\nmain()")]
os.chdir(os.path.join(os.environ.get("TEMP", "/tmp")))   # main.py writes log.txt in the working directory
ns = {"__name__": "sign_main"}
exec(compile(src, "main.py", "exec"), ns)

ns["state"]["clock_ok"] = True
ns["poll_data"](); ns["poll_hosts"](); ns["poll_uptime"](); ns["poll_trend"]()
st = ns["state"]
print("air", st["temp_f"], "hum", st["hum"], "water", st.get("water_f"), "err", st["err"])
print("hosts", st["hosts"])
print("uptime", st["uptime"])
print("trend points", {k: sum(v is not None for v in vals) for k, vals in st["trend"].items()})
print("shows get", ns["demo_hosts"](), "| demo gets", len(ns["demo_hosts"](fill=4)))

g = ns["gfx"]
frames, labels = [], []
for label, draw in (("AIR", lambda: ns["draw_temp"](True)), ("WATER", lambda: ns["draw_water"](True)),
                    ("HUMIDITY", lambda: ns["draw_hum"](True))):
    g.set_pen(ns["BLACK"]); g.clear(); draw(); ns["draw_hosts"]()
    frames.append([r[:] for r in g.fb]); labels.append(label)
ns["scroll_x"] = 2
g.set_pen(ns["BLACK"]); g.clear(); ns["draw_names"]()
frames.append([r[:] for r in g.fb]); labels.append("UPTIME scroll")
sheet(frames, labels, out)
print("wrote", out)
