"""Run the sign's main.py on the PC against a real TankWatch hub, with the Pico hardware faked, and save
each screen as a contact sheet. Checks the config, the hub queries and the drawing without a board.

Usage: python sim_main.py CONFIG.json TOKEN out.png
  CONFIG.json  the sign's config (hub_url must be reachable from this PC)
  TOKEN        a read-only token (hub/.env INFLUX_READ_TOKEN)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emulator                       # noqa: E402  fake Pico hardware
from sim_gfx import sheet             # noqa: E402

cfg_path, token, out = sys.argv[1], sys.argv[2], sys.argv[3]
emulator.install(token)
cfg_path = os.path.abspath(cfg_path)
os.chdir(os.environ.get("TEMP", "/tmp"))   # main.py writes log.txt in the working directory
ns = emulator.load_main(cfg_path)

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
