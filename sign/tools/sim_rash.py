"""Preview roadrash.py on the PC: contact sheet of frames across one race. Usage: python sim_rash.py out.png"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # the shows live one folder up
from sim_gfx import FakeGfx, sheet
import roadrash

info = {"hosts": [("N1", "up", 128, 1.0, None), ("N2", "warn", 172, 0.998, "HOT"),
                  ("N3", "up", 131, 0.992, None), ("HUB", "down", None, 0.95, None)],
        "tank": (71.8, 62.0, 77.1)}
g = FakeGfx()
frames, labels = [], []
picks = [int(a) for a in (sys.argv[2].split(",") if len(sys.argv) > 2 else
         "500,1800,2700,3600,4800,5900,7000,9000,10800,12500,14000,16300,18000,20400,23000,26000,28000,30500,33000".split(","))]
ms, end = 0, None
while ms <= max(picks):
    roadrash.frame(g, ms, info)
    if ms in picks:
        frames.append([row[:] for row in g.fb])
        labels.append("t=%.1fs" % (ms / 1000))
    ms += 20
print("race end at %.1fs" % (roadrash.race["end"] / 1000), "events:", [(e[0], e[1]) for e in roadrash.race["events"]])
sheet(frames, labels, sys.argv[1])
