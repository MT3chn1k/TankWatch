"""Fake Pico 2 W hardware, so the sign's real main.py runs unchanged on a PC: used by sim_main.py (one-off
screenshots) and virtual_sign.py (the sign in a web browser).

install(token, on_update) replaces MicroPython's machine, network, rp2, ntptime, urequests, galactic,
picographics and secrets modules, and adds MicroPython's extra time functions. Every gu.update(gfx) main.py
makes calls on_update(framebuffer) with the frame as a flat list of (r, g, b), row by row.
"""
import calendar, os, sys, time, types, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_gfx import FakeGfx, W, H  # noqa: E402  (also installs a fake micropython module)

SIGN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m


class _Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text

    def close(self):
        pass


def _post(url, data=None, headers=None, timeout=5):
    req = urllib.request.Request(url, data=data.encode(), headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _Resp(r.status, r.read().decode())
    except urllib.error.HTTPError as e:
        return _Resp(e.code, e.read().decode())


class _Wlan:
    def __init__(self, *a): pass
    def active(self, *a): pass
    def config(self, **k): pass
    def connect(self, *a): pass
    def isconnected(self): return True
    def status(self): return 3
    def ifconfig(self): return ("127.0.0.1",)


def install(token, on_update=None):
    class Unicorn:
        WIDTH, HEIGHT = W, H
        # MicroPython's GalacticUnicorn exposes its buttons as class constants
        SWITCH_A, SWITCH_B, SWITCH_C, SWITCH_D = 0, 1, 3, 6
        SWITCH_SLEEP, SWITCH_VOLUME_UP, SWITCH_VOLUME_DOWN = 27, 7, 8
        SWITCH_BRIGHTNESS_UP, SWITCH_BRIGHTNESS_DOWN = 21, 26

        def set_brightness(self, b): pass
        def is_pressed(self, k): return False

        def update(self, g):
            if on_update:
                on_update([px for row in g.fb for px in row])

    _stub("machine", freq=lambda *a: 150000000, reset=lambda: None)
    _stub("network", WLAN=_Wlan, STA_IF=0, STAT_CONNECTING=1)
    _stub("rp2", country=lambda c: None)
    _stub("ntptime", settime=lambda: None, timeout=3, host="")
    _stub("urequests", post=_post)
    _stub("galactic", GalacticUnicorn=Unicorn)
    _stub("picographics", PicoGraphics=lambda d: FakeGfx(), DISPLAY_GALACTIC_UNICORN=0)
    _stub("secrets", WIFI_SSID="", WIFI_PASSWORD="", INFLUX_TOKEN=token)
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
    time.ticks_diff = lambda a, b: a - b
    time.ticks_add = lambda a, b: a + b
    time.sleep_ms = lambda ms: time.sleep(ms / 1000)
    time.mktime = lambda t: int(calendar.timegm(tuple(t[:6]) + (0, 0, 0)))   # MicroPython: UTC, 8-tuple


def load_main(config_path, run=False):
    """Compile the sign's main.py reading config_path. run=False stops before its endless main() loop and
    returns its globals; run=True runs it (never returns)."""
    src = open(os.path.join(SIGN_DIR, "main.py"), encoding="utf-8").read()
    src = src.replace('open("config.json")', "open(%r)" % config_path)
    if not run:
        src = src[:src.rstrip().rfind("\nmain()")]
    ns = {"__name__": "sign_main"}
    exec(compile(src, "main.py", "exec"), ns)
    return ns
