# Run on the board with: python -m mpremote connect COM6 run rash_bench.py
# Plays one Road Rash race through roadrash.frame() at the same 50 fps cap as main.py, with sample
# numbers, and prints the frame rate. Reset the board afterwards to restart main.py.
import time
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
import roadrash

gu = GalacticUnicorn()
gfx = PicoGraphics(DISPLAY)
gu.set_brightness(0.5)
info = {"hosts": [("N1", "up", 128, 1.0, None), ("N2", "warn", 172, 0.998, "HOT"),
                  ("N3", "up", 131, 0.992, None), ("HUB", "down", None, 0.95, None)], "tank": (71.8, 62.0, 77.1)}
roadrash.restart()
ms, n, slow = 0, 0, 0
last = time.ticks_ms()
while True:
    tick = time.ticks_ms()
    ms += time.ticks_diff(tick, last)
    last = tick
    roadrash.frame(gfx, ms, info)
    gu.update(gfx)
    n += 1
    used = time.ticks_diff(time.ticks_ms(), tick)
    slow = max(slow, used)
    if roadrash.race["start"] is None:  # results finished, race restarted
        break
    time.sleep_ms(20 - used if used < 19 else 1)
print("race + results %.1f s, %.1f fps, slowest frame %d ms" % (ms / 1000, n * 1000 / ms, slow))
