#!/usr/bin/env python3
"""TankWatch collector: reads the sensors listed in tankwatch.yaml and sends them to the hub's InfluxDB.

Each sensor runs on its own interval. Readings that can't be sent (hub down, network out) are kept in
memory and sent with the next successful write, up to BUFFER_MAX lines, so a short outage loses nothing.
If the hub stays unreachable for REDISCOVER_AFTER_S, the collector looks for the same hub (by its id) on the
network, and if it has moved to a new address, switches to it and saves the new address in tankwatch.yaml.

Config: tankwatch.yaml (written by setup.sh). The older layout, config.yaml plus INFLUX_* variables in .env,
still works. A join code in TANKWATCH_JOIN (or `join:` in the file) fills in the hub on first start.
"""
import importlib, logging, os, re, socket, sys, time, urllib.error, urllib.parse, urllib.request
from collections import deque

import yaml

import discovery

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tankwatch")

BUFFER_MAX = 10000
REDISCOVER_AFTER_S = int(os.environ.get("TANKWATCH_REDISCOVER_AFTER_S", 180))   # unreachable this long: look for the hub
REDISCOVER_EVERY_S = int(os.environ.get("TANKWATCH_REDISCOVER_EVERY_S", 300))   # and don't search more often than this


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
    def __init__(self, url, org, bucket, token, hub_id=None, config_path=None):
        self.org, self.bucket, self.token, self.hub_id, self.config_path = org, bucket, token, hub_id, config_path
        self.pending = deque(maxlen=BUFFER_MAX)
        self.failing_since = None
        self.last_search = 0.0
        self.set_url(url)

    def set_url(self, url):
        self.url = url.rstrip("/")
        q = urllib.parse.urlencode({"org": self.org, "bucket": self.bucket, "precision": "s"})
        self.endpoint = "%s/api/v2/write?%s" % (self.url, q)

    def unreachable(self):
        """Called after a failed send. After REDISCOVER_AFTER_S of failures, look for the hub elsewhere."""
        now = time.time()
        self.failing_since = self.failing_since or now
        if not self.hub_id or now - self.failing_since < REDISCOVER_AFTER_S or now - self.last_search < REDISCOVER_EVERY_S:
            return
        self.last_search = now
        log.info("hub at %s unreachable for %d s; looking for hub %s on the network", self.url,
                 now - self.failing_since, self.hub_id)
        hubs = discovery.find_hubs(hub_id=self.hub_id, hints=[discovery.host_of(self.url)])
        if not hubs:
            log.warning("hub %s not found on the network; will look again in %d min", self.hub_id, REDISCOVER_EVERY_S // 60)
            return
        if hubs[0]["url"] == self.url:
            log.info("hub %s answers at its usual address again", self.hub_id)
            return
        old = self.url
        self.set_url(hubs[0]["url"])
        log.warning("hub %s moved: %s -> %s; switching", self.hub_id, old, self.url)
        save_hub_url(self.config_path, old, self.url)

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
            self.unreachable()
            return
        if self.failing_since:
            log.info("hub reachable again after %d s; sent %d buffered lines", time.time() - self.failing_since, len(batch))
        self.failing_since = None
        self.pending.clear()
        log.debug("sent %d lines", len(batch))


def save_hub_url(path, old, new):
    """Record the hub's new address in the config file, changing only that one value so comments survive."""
    if not path or not os.access(path, os.W_OK):
        log.warning("can't save the new hub address (config file not writable); it will be found again after a restart")
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # the url line may be quoted (setup.sh writes "http://...") or bare (hand-written)
    updated = re.sub(r'(?m)^(\s*url:\s*)"?%s"?\s*$' % re.escape(old), lambda m: m.group(1) + '"%s"' % new, text, count=1)
    if updated != text:
        # The file is bind-mounted on its own, so it can't be replaced by renaming a temporary file. Keep the window
        # where it's incomplete as short as possible: one write of the whole text, then force it to disk.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(updated)
            fh.flush()
            os.fsync(fh.fileno())
        log.info("saved new hub address in %s (was %s)", path, old)


def load_config():
    """tankwatch.yaml, or the older config.yaml (+ INFLUX_* env vars). Returns (config dict, path)."""
    path = os.environ.get("TANKWATCH_CONFIG")
    if not path:
        path = next((p for p in ("/config/tankwatch.yaml", "tankwatch.yaml", "/config/config.yaml", "config.yaml")
                     if os.path.exists(p)), "tankwatch.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except PermissionError:
        raise SystemExit("can't read %s: it belongs to another user. Run ./setup.sh again as the user who set this "
                         "collector up (setup.sh records that user for the container)." % path)
    except OSError as e:
        raise SystemExit("can't read %s (%s). Run ./setup.sh to create it." % (path, e.strerror))
    if not text.strip():
        raise SystemExit("%s is empty (perhaps a power cut while it was being saved). Run ./setup.sh again with the "
                         "hub's join code to rewrite it." % path)
    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = " at line %d" % (mark.line + 1) if mark else ""
        raise SystemExit("%s is damaged%s, so it can't be read. Run ./setup.sh again to rewrite it (with the hub's join "
                         "code if it asks)." % (path, where))
    if not isinstance(cfg, dict):
        raise SystemExit("%s doesn't look like a TankWatch config. Run ./setup.sh again to rewrite it." % path)
    return cfg, path


def hub_settings(cfg):
    """Hub details from, in order of priority: INFLUX_* env vars, the config's hub: section, a join code."""
    hub = dict(cfg.get("hub") or {})
    code = os.environ.get("TANKWATCH_JOIN") or cfg.get("join")
    if code and not hub.get("token"):
        j = discovery.decode_join(code)
        if j["role"] != "collector":
            raise SystemExit("that join code is for a display (read-only); a collector needs the collector join code")
        hub = {"id": j["id"], "url": j["url"], "org": j["org"], "bucket": j["bucket"], "token": j["token"]}
    for key, env in (("url", "INFLUX_URL"), ("org", "INFLUX_ORG"), ("bucket", "INFLUX_BUCKET"), ("token", "INFLUX_TOKEN")):
        if os.environ.get(env):
            hub[key] = os.environ[env]
    return hub


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


def test_sensors(cfg):
    """--test: read every configured sensor once and print what it says. Doesn't contact the hub."""
    ok = True
    for i, spec in enumerate(cfg.get("sensors") or []):
        check_type(spec["type"])
        name = spec.get("name") or "%s-%d" % (spec["type"], i)
        try:
            sensor = importlib.import_module("sensors." + spec["type"]).Sensor(spec.get("options") or {})
            for measurement, tags, fields in sensor.read():
                extra = " ".join("%s=%s" % kv for kv in tags.items() if kv[1])
                print("OK    %-14s %-11s %s %s" % (name, measurement, " ".join("%s=%s" % kv for kv in fields.items()), extra))
        except Exception as e:
            ok = False
            print("FAIL  %-14s %s: %s" % (name, type(e).__name__, e))
    return ok


def main():
    cfg, path = load_config()
    if "--test" in sys.argv:
        sys.exit(0 if test_sensors(cfg) else 1)
    node = os.environ.get("TANKWATCH_NODE") or cfg.get("node") or socket.gethostname()
    h = hub_settings(cfg)
    if not h.get("token"):
        raise SystemExit("no hub settings: run setup.sh, or put a join code in TANKWATCH_JOIN")
    if not h.get("url") and h.get("id"):
        found = discovery.find_hubs(hub_id=h["id"])
        if not found:
            raise SystemExit("couldn't find the hub on the network; put its address in tankwatch.yaml (hub: url:)")
        h["url"] = found[0]["url"]
    hub = Hub(h.get("url", ""), h.get("org", "tankwatch"), h.get("bucket", "sensors"), h["token"],
              hub_id=h.get("id"), config_path=path)
    if "://" not in hub.endpoint:
        raise SystemExit("the hub address in %s isn't a URL (expected something like http://192.168.1.10:8086)" % path)
    log.info("collector %s sending to %s (hub %s)", node, hub.url, h.get("id") or "-")

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
