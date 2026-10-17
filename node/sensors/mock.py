"""Fake temperature and humidity readings, for trying TankWatch without any hardware wired up."""
import math, random, time

from . import c_to_f


class Sensor:
    def __init__(self, options):
        self.measurement = options.get("measurement", "air")
        self.base_c = float(options.get("base_c", 22.0))

    def read(self):
        c = round(self.base_c + 1.5 * math.sin(time.time() / 600) + random.uniform(-0.2, 0.2), 2)
        return [(self.measurement, {"sensor": "mock"},
                 {"temp_c": c, "temp_f": c_to_f(c), "humidity": round(random.uniform(45, 60), 1)})]
