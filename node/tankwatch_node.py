#!/usr/bin/env python3
"""TankWatch node agent: reads the sensors listed in config.yaml and sends them to the hub's InfluxDB.

Each sensor runs on its own interval. Readings that can't be sent (hub down, network out) are kept in
memory and sent with the next successful write, up to BUFFER_MAX lines, so a short outage loses nothing.
"""
import importlib, logging, os, socket, sys, time, urllib.error, urllib.parse, urllib.request
from collections import deque

import yaml

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tankwatch")

BUFFER_MAX = 10000


def esc_tag(v):
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def fmt_field(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return "%di" % v
    if isinstance(v, float):
        return repr(v)
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def line(measurement, tags, fields, ts):
    t = "".join(",%s=%s" % (esc_tag(k), esc_tag(v)) for k, v in sorted(tags.items()) if v not in (None, ""))
    f = ",".join("%s=%s" % (esc_tag(k), fmt_field(v)) for k, v in fields.items() if v is not None)
    return "%s%s %s %d" % (esc_tag(measurement), t, f, ts)


class Hub:
    def __init__(self, url, org, bucket, token):
        q = urllib.parse.urlencode({"org": org, "bucket": bucket, "precision": "s"})
        self.endpoint = "%s/api/v2/write?%s" % (url.rstrip("/"), q)
        self.token = token
        self.pending = deque(maxlen=BUFFER_MAX)

    def send(self, lines):
        self.pending.extend(lines)
        if not self.pending:
            return
        batch = list(self.pending)
        req = urllib.request.Request(self.endpoint, data="\n".join(batch).encode(), method="POST",
                                     headers={"Authorization": "Token " + self.token, "Content-Type": "text/plain"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if 400 <= e.code < 500 and e.code != 429:
                # The hub rejected the data itself (bad token, bad line). Retrying won't help, so drop the batch.
                log.error("hub rejected %d lines (HTTP %d): %s", len(batch), e.code, body)
                self.pending.clear()
            else:
                log.warning("hub error HTTP %d, keeping %d lines for retry", e.code, len(self.pending))
            return
        except Exception as e:
            log.warning("hub unreachable (%s), keeping %d lines for retry", e, len(self.pending))
            return
        self.pending.clear()
        log.debug("sent %d lines", len(batch))


RETRY_INIT_S = 300


def check_type(kind):
    """A sensor type with no file in sensors/ is a typo in config.yaml: stop with a clear message."""
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensors", kind + ".py")):
        known = sorted(f[:-3] for f in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensors"))
                       if f.endswith(".py") and not f.startswith("_"))
        raise SystemExit("unknown sensor type '%s' in config.yaml; known types: %s" % (kind, ", ".join(known)))


def start_sensor(job):
    """Set up a sensor's hardware. If it fails (not wired, wrong pin, no access to GPIO), log why and try again
    in RETRY_INIT_S; the node's other sensors keep running meanwhile."""
    try:
        mod = importlib.import_module("sensors." + job["type"])
        job["sensor"] = mod.Sensor(job["options"])
        if job.get("failed"):
            log.info("%s: started after earlier failures", job["name"])
        job["failed"] = False
    except Exception as e:
        job["sensor"] = None
        job["retry_at"] = time.time() + RETRY_INIT_S
        job["failed"] = True
        log.error("%s (%s): could not start: %s: %s. Check its wiring and the options/pin in config.yaml, and "
                  "that docker-compose.yml gives the container this hardware. Retrying in %d min.",
                  job["name"], job["type"], type(e).__name__, e, RETRY_INIT_S // 60)


def main():
    path = os.environ.get("TANKWATCH_CONFIG", "config.yaml")
    with open(path) as fh:
        cfg = yaml.safe_load(fh) or {}

    node = cfg.get("node") or os.environ.get("TANKWATCH_NODE") or socket.gethostname()
    hub_cfg = cfg.get("hub") or {}
    hub = Hub(os.environ.get("INFLUX_URL", hub_cfg.get("url", "")),
              os.environ.get("INFLUX_ORG", hub_cfg.get("org", "tankwatch")),
              os.environ.get("INFLUX_BUCKET", hub_cfg.get("bucket", "sensors")),
              os.environ.get("INFLUX_TOKEN", ""))
    if not hub.token or "://" not in hub.endpoint:
        raise SystemExit("set INFLUX_URL and INFLUX_TOKEN (see .env.example)")

    jobs = []
    for i, spec in enumerate(cfg.get("sensors") or []):
        name = spec.get("name") or "%s-%d" % (spec["type"], i)
        check_type(spec["type"])
        tags = {"node": node, "location": spec.get("location", ""), **(spec.get("tags") or {})}
        jobs.append({"name": name, "type": spec["type"], "options": spec.get("options") or {}, "tags": tags,
                     "every": int(spec.get("interval_s", 60)), "due": 0.0, "sensor": None})
        log.info("sensor %s (%s) every %ss, location=%s", name, spec["type"], jobs[-1]["every"], tags["location"] or "-")
    if not jobs:
        raise SystemExit("no sensors in %s" % path)
    for j in jobs:
        start_sensor(j)

    while True:
        now = time.time()
        lines = []
        for j in jobs:
            if now < j["due"]:
                continue
            j["due"] = now + j["every"]
            if j["sensor"] is None:
                if now >= j["retry_at"]:
                    start_sensor(j)
                if j["sensor"] is None:
                    continue
            try:
                readings = j["sensor"].read()
            except Exception as e:
                log.warning("%s: read failed: %s", j["name"], e)
                continue
            for measurement, tags, fields in readings:
                lines.append(line(measurement, {**j["tags"], **tags}, fields, int(now)))
                log.info("%s: %s %s", j["name"], measurement, " ".join("%s=%s" % kv for kv in fields.items()))
        if lines or hub.pending:
            hub.send(lines)
        time.sleep(max(0.5, min(j["due"] for j in jobs) - time.time()))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
