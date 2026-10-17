# Run on the board with: python -m mpremote connect COM6 run demo_bench.py
# Plays one full demo loop through demo.frame() (as main.py does, capped at 50 fps) with sample
# statuses and prints each scene's length and frame rate. Reset the board afterwards to restart main.py.
import time
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
import demo

gu = GalacticUnicorn()
gfx = PicoGraphics(DISPLAY)
gu.set_brightness(0.5)
hosts = [("N1", "up", 128, 1.0, None), ("N2", "warn", 172, 0.998, "HOT"),
         ("N3", "up", 131, 0.992, None), ("HUB", "down", None, 0.95, None)]
demo.restart()
ms = 0
last = time.ticks_ms()
scene, n, t0, laps = 0, 0, 0, 0
while True:
    tick = time.ticks_ms()
    ms += time.ticks_diff(tick, last)
    last = tick
    demo.frame(gfx, ms, hosts)
    gu.update(gfx)
    n += 1
    if demo._seq["i"] != scene:
        print("%-15s %5.1f s %5.1f fps" % (demo.SCENES[scene].__name__, (ms - t0) / 1000, n * 1000 / max(1, ms - t0)))
        scene, n, t0 = demo._seq["i"], 0, ms
        if scene == 0:
            break
    spare = 20 - time.ticks_diff(time.ticks_ms(), tick)
    time.sleep_ms(spare if spare > 1 else 1)
