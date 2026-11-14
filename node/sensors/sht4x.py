"""Sensirion SHT40 / SHT41 / SHT45 air temperature and humidity on I2C (SDA = GPIO2, SCL = GPIO3).

Needs I2C switched on (sudo raspi-config nonint do_i2c 0, or dtparam=i2c_arm=on in /boot/firmware/config.txt).
Talks to the kernel's /dev/i2c-N directly, so it needs no extra Python packages.

options:
  bus: 1          (default 1: /dev/i2c-1, the Pi's header pins)
  address: 0x44   (default 0x44; some boards use 0x45 or 0x46)
"""
import fcntl, os, time

from . import c_to_f

I2C_SLAVE = 0x0703          # ioctl: talk to this device address on the bus
MEASURE_HIGH = 0xFD         # high-precision measurement, heater off
MEASURE_TIME_S = 0.01       # the datasheet's longest high-precision measurement is 8.3 ms


def crc8(data):
    """Sensirion CRC-8: polynomial 0x31, starting value 0xFF."""
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def decode(raw):
    """The sensor's 6-byte answer -> (temp_c, humidity). Raises ValueError if a checksum doesn't match."""
    if len(raw) != 6:
        raise ValueError("short answer (%d bytes)" % len(raw))
    if crc8(raw[0:2]) != raw[2] or crc8(raw[3:5]) != raw[5]:
        raise ValueError("checksum mismatch")
    t = -45 + 175 * ((raw[0] << 8) | raw[1]) / 65535
    h = -6 + 125 * ((raw[3] << 8) | raw[4]) / 65535
    return t, min(100.0, max(0.0, h))       # the datasheet says to clip humidity to 0-100 %


class Sensor:
    def __init__(self, options):
        self.path = "/dev/i2c-%d" % int(options.get("bus", 1))
        address = options.get("address", 0x44)
        self.address = int(address, 0) if isinstance(address, str) else int(address)

    def measure(self):
        fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, self.address)
            os.write(fd, bytes([MEASURE_HIGH]))
            time.sleep(MEASURE_TIME_S)
            return os.read(fd, 6)
        finally:
            os.close(fd)

    def read(self):
        # Another program reading the same sensor can now and then spoil an answer; the checksum catches it.
        error = None
        for _ in range(3):
            try:
                t, h = decode(self.measure())
                if not -40 <= t <= 125:                 # outside the sensor's range: not a real reading
                    raise ValueError("implausible temperature %.1f C" % t)
                return [("air", {"sensor": "sht4x"},
                         {"temp_c": round(t, 2), "temp_f": c_to_f(t), "humidity": round(h, 1)})]
            except (OSError, ValueError) as e:
                error = e
                time.sleep(1)
        raise RuntimeError("no valid reading from %s address 0x%02x: %s" % (self.path, self.address, error))
