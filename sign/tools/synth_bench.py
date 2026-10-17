# Run on the board with: python -m mpremote connect COM6 run synth_bench.py
import time
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
import synthwave

gu = GalacticUnicorn()
gfx = PicoGraphics(DISPLAY)
gu.set_brightness(0.5)
info = {"hosts": [("N1", "up", 128, 1.0, None), ("N2", "warn", 172, 0.998, "HOT"),
                  ("N3", "up", 131, 0.992, None), ("HUB", "down", None, 0.95, None)], "tank": (71.8, 62.0, 77.1)}
t0 = time.ticks_ms(); n = 0
while time.ticks_diff(time.ticks_ms(), t0) < 6000:
    synthwave.frame(gfx, time.ticks_diff(time.ticks_ms(), t0), info)
    gu.update(gfx); n += 1
print("synthwave %.1f fps" % (n / 6))
