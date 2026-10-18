"""Realistic made-up readings, for demos and the test lab. Driven by the clock, so a restarted collector
carries on the same curves instead of jumping.

options:
  profile: tank | room | plant | feeder    (default tank)
  base_c: 25.0      tank / room: the average temperature
  phase_h: 0        shifts this sensor's cycles by some hours, so several of the same profile don't move in step

Profiles:
  tank    measurement water: heater cycling about +-0.3 C every ~25 min, a slow day/night drift, and a daily
          water change at 17:00 (1.5 C cooler, recovering over ~40 min)
  room    measurement air: warmest mid-afternoon, humidity moving the other way
  plant   measurement soil, field moisture_pct: dries out over about 3 days, then is watered back to ~70 %
  feeder  measurement level, field level_pct: an automatic feeder; drops at each of 3 daily feeds, refilled
          when it gets low (every ~5 days)
"""
import math, random, time

from . import c_to_f

DAY = 86400.0


class Sensor:
    def __init__(self, options):
        self.profile = options.get("profile", "tank")
        if self.profile not in ("tank", "room", "plant", "feeder"):
            raise ValueError("synthetic profile must be tank, room, plant or feeder, not %r" % self.profile)
        self.base_c = float(options.get("base_c", 25.0 if self.profile == "tank" else 21.0))
        self.phase = float(options.get("phase_h", 0)) * 3600

    def read(self):
        t = time.time() + self.phase
        local = time.localtime(t)
        hour = local.tm_hour + local.tm_min / 60 + local.tm_sec / 3600
        day_curve = math.sin((hour - 9) / 24 * 2 * math.pi)          # +1 mid-afternoon, -1 around 3 am
        return getattr(self, "_" + self.profile)(t, hour, day_curve)

    def _tank(self, t, hour, day_curve):
        c = self.base_c + 0.25 * day_curve + 0.3 * math.sin(t / 1500 * 2 * math.pi)
        since_change = hour - 17.0
        if 0 <= since_change < 0.7:                                    # water change, then the heater catches up
            c -= 1.5 * math.sin(since_change / 0.7 * math.pi)
        c = round(c + random.uniform(-0.03, 0.03), 2)
        return [("water", {"sensor": "synthetic"}, {"temp_c": c, "temp_f": c_to_f(c)})]

    def _room(self, t, hour, day_curve):
        c = round(self.base_c + 1.6 * day_curve + random.uniform(-0.1, 0.1), 1)
        hum = round(52 - 6 * day_curve + random.uniform(-0.8, 0.8), 1)
        return [("air", {"sensor": "synthetic"}, {"temp_c": c, "temp_f": c_to_f(c), "humidity": hum})]

    def _plant(self, t, hour, day_curve):
        cycle = 3.2 * DAY
        dried = (t % cycle) / cycle                                    # 0 just watered .. 1 about to be watered
        moisture = 72 - 42 * dried ** 0.8 - 1.5 * max(day_curve, 0)    # dries a little faster in the afternoon
        return [("soil", {"sensor": "synthetic"}, {"moisture_pct": round(moisture + random.uniform(-0.4, 0.4), 1)})]

    def _feeder(self, t, hour, day_curve):
        feeds = int(t // (DAY / 3))                                    # three feeds a day
        level = 100 - 5.5 * (feeds % 15)                               # refilled every 15 feeds (5 days)
        return [("level", {"sensor": "synthetic"}, {"level_pct": round(float(level), 1)})]
