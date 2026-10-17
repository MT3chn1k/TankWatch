"""DHT11 / DHT22 air temperature and humidity on a GPIO pin.

options:
  model: dht11 | dht22   (default dht11)
  pin: D17               (board pin name; D17 = GPIO17 = physical pin 11)
"""
import time

import adafruit_dht
import board

from . import c_to_f


class Sensor:
    def __init__(self, options):
        self.model = options.get("model", "dht11").lower()
        cls = adafruit_dht.DHT22 if self.model == "dht22" else adafruit_dht.DHT11
        self.dev = cls(getattr(board, options.get("pin", "D4")), use_pulseio=False)

    def read(self):
        # DHT sensors miss reads often; try a few times, 2.5 s apart (they can't be read faster).
        for _ in range(6):
            try:
                t, h = self.dev.temperature, self.dev.humidity
                if t is not None and h is not None:
                    t = float(t)
                    return [("air", {"sensor": self.model}, {"temp_c": t, "temp_f": c_to_f(t), "humidity": float(h)})]
            except RuntimeError:
                pass
            time.sleep(2.5)
        raise RuntimeError("no valid reading after 6 tries")
