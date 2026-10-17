"""DS18B20 waterproof temperature probes on the 1-Wire bus (GPIO4 by default). Every probe found is read,
tagged with its serial number. Needs `dtoverlay=w1-gpio` in /boot/firmware/config.txt.

options:
  measurement: water     (default water)
  names: {28-1f3b...: left-tank}   optional friendly name per probe serial, stored as tag `probe_name`
"""
import glob, os

from . import c_to_f

W1 = os.environ.get("W1_DEVICES", "/sys/bus/w1/devices")


def plausible(c):
    # 85.0 is the DS18B20 power-on value and -127 its read error; neither is a real reading.
    return -10 < c < 60 and c != 85.0


class Sensor:
    def __init__(self, options):
        self.measurement = options.get("measurement", "water")
        self.names = options.get("names") or {}

    def read(self):
        out = []
        probes = sorted(glob.glob(os.path.join(W1, "28-*")))
        if not probes:
            raise RuntimeError("no DS18B20 probe found under %s" % W1)
        for p in probes:
            serial = os.path.basename(p)
            with open(os.path.join(p, "w1_slave")) as fh:
                crc_line, data_line = fh.read().splitlines()[:2]
            if not crc_line.endswith("YES"):
                continue
            c = int(data_line.rsplit("t=", 1)[1]) / 1000
            if plausible(c):
                tags = {"sensor": "ds18b20", "probe": serial, "probe_name": self.names.get(serial, "")}
                out.append((self.measurement, tags, {"temp_c": round(c, 2), "temp_f": c_to_f(c)}))
        return out
