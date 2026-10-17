"""Health of the computer running the agent: CPU temperature, Raspberry Pi undervolt/throttle flags,
core and 5 V input voltage (when vcgencmd is available), load, memory and disk use.

Works in a container: CPU temperature and throttle flags come from /sys, load and memory from /proc
(both show the host). Mount the host's root read-only at /host to report the host's disk, not the
container's.

options:
  disk_path: /host       (default: /host if it exists, else /)
"""
import os, re, shutil, subprocess

from . import c_to_f

THROTTLE_SYSFS = "/sys/devices/platform/soc/soc:firmware/get_throttled"
FLAGS = (("undervolt_now", 0), ("freqcap_now", 1), ("throttled_now", 2), ("templimit_now", 3),
         ("undervolt_occurred", 16), ("freqcap_occurred", 17), ("throttled_occurred", 18), ("templimit_occurred", 19))


def vc(*args):
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def num(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


class Sensor:
    def __init__(self, options):
        self.disk = options.get("disk_path") or ("/host" if os.path.isdir("/host") else "/")

    def read(self):
        f = {}
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as fh:
                t = int(fh.read()) / 1000
            f["temp_c"], f["temp_f"] = round(t, 1), c_to_f(t)
        except OSError:
            pass
        raw = None
        try:
            with open(THROTTLE_SYSFS) as fh:
                raw = int(fh.read().strip(), 16)
        except (OSError, ValueError):
            m = re.search(r"0x([0-9a-fA-F]+)", vc("get_throttled"))
            raw = int(m.group(1), 16) if m else None
        if raw is not None:
            f["throttled_raw"] = raw
            for name, bit in FLAGS:
                f[name] = (raw >> bit) & 1
        core = num(vc("measure_volts", "core"), r"volt=([\d.]+)V")
        if core is not None:
            f["core_v"] = core
        ext5 = num(vc("pmic_read_adc", "EXT5V_V"), r"EXT5V_V.*?=([\d.]+)V")
        if ext5 is not None:
            f["ext5v_v"] = ext5
        f["load1"] = round(os.getloadavg()[0], 2)
        with open("/proc/meminfo") as fh:
            mem = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in fh)}
        f["mem_used_pct"] = round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"]), 1)
        du = shutil.disk_usage(self.disk)
        f["disk_used_pct"] = round(100 * du.used / du.total, 1)
        return [("node_health", {}, f)]
