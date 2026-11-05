#!/usr/bin/env python3
"""TankWatch widget service (optional add-on): a small read-only summary for the phone widget.

Runs on the hub next to InfluxDB when you turn it on (see hub/docker-compose.yml):
    docker compose --profile widget up -d

It answers only two requests, and only for a paired phone (each phone has its own token, sent as
"Authorization: Bearer <token>"):
    GET /v1/info      which hub this is, and the healthy ranges
    GET /v1/summary   latest readings per location and every collector's status, with the same rules as the displays
Anything else, or a missing or unknown token, gets 404. /healthz is open (for Docker's health check).
It reads InfluxDB with the read-only token and can't change anything on the hub. Standard library only.

Pairing a phone (step 1: from the hub's command line; the admin page gets a button and a QR code later):
    docker compose exec widget python widget.py pair "Steven's phone"    prints the pairing link
    docker compose exec widget python widget.py list
    docker compose exec widget python widget.py revoke <id>
Tokens are stored only as SHA-256 hashes, in /data/devices.json (the widget-data volume).

Settings come from environment variables (hub/docker-compose.yml passes them from hub/.env):
  INFLUX_URL                     where InfluxDB is (default http://influxdb:8086)
  INFLUX_ORG, INFLUX_BUCKET, INFLUX_READ_TOKEN
  HUB_ID, HUB_NAME               which hub this is
  WIDGET_PORT                    default 8089
  WIDGET_ADDRESS                 the address phones use at home (default HUB_ADDRESS, else HUB_DETECTED_ADDRESS)
  WIDGET_PUBLIC_PORT             the port phones use (default WIDGET_PORT)
  WIDGET_REMOTE_URL              optional address for away from home, e.g. http://100.101.102.103:8089 (Tailscale)
  WATER_RANGE_F, AIR_RANGE_F     healthy ranges in °F, "low,high" (default 74,82 and 68,80, as the status sign)
  WIDGET_DATA                    where devices.json lives (default /data)
  WIDGET_TRUSTED_PROXIES         addresses whose X-Forwarded-For is believed (default: loopback and Docker's
                                 172.16.0.0/12, i.e. a proxy on the hub itself such as Tailscale Funnel)
"""
import csv, hashlib, hmac, io, ipaddress, json, logging, os, re, secrets, signal, sys, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s widget: %(message)s")
log = logging.getLogger()

E = os.environ.get
PORT = int(E("WIDGET_PORT", "8089"))
INFLUX = E("INFLUX_URL", "http://influxdb:8086").rstrip("/")
ORG, BUCKET, READ_TOKEN = E("INFLUX_ORG", "tankwatch"), E("INFLUX_BUCKET", "sensors"), E("INFLUX_READ_TOKEN", "")
DATA = E("WIDGET_DATA", "/data")
DEVICES = os.path.join(DATA, "devices.json")

SILENT_S, HOT_C, STALE_S = 90, 77, 15 * 60     # same rules as the displays and the status sign
MAX_FAILS, FAIL_WINDOW_S = 20, 600             # wrong tokens from one address before it's ignored for 10 minutes
SEEN_FLUSH_S = 600                             # write "last seen" times to disk at most this often


def frange(name, default):
    try:
        lo, hi = (float(x) for x in (E(name) or default).split(","))
        return [min(lo, hi), max(lo, hi)]
    except ValueError:
        log.warning("%s should look like 74,82; using %s", name, default)
        return [float(x) for x in default.split(",")]


RANGES = {"water": frange("WATER_RANGE_F", "74,82"), "air": frange("AIR_RANGE_F", "68,80")}


# ------------------------------------------------------------------------------------------------ InfluxDB
def b(s):
    """A Flux string literal."""
    return json.dumps(s)


def flux(q, timeout=10):
    req = urllib.request.Request("%s/api/v2/query?org=%s" % (INFLUX, urllib.parse.quote(ORG)), data=q.encode(),
                                 method="POST", headers={"Authorization": "Token " + READ_TOKEN,
                                                         "Content-Type": "application/vnd.flux", "Accept": "application/csv"})
    body = urllib.request.urlopen(req, timeout=timeout).read().decode()
    rows, head = [], None
    for rec in csv.reader(io.StringIO(body)):
        if len(rec) < 3:
            continue
        if rec[1] == "result":
            head = rec
        elif head:
            rows.append(dict(zip(head, rec)))
    return rows


def ago(s):
    s = int(s)
    return "%d s" % s if s < 120 else "%d min" % (s // 60) if s < 7200 else "%d h" % (s // 3600) if s < 172800 \
        else "%d days" % (s // 86400)


def collectors(now):
    """Every collector heard from in the last 24 h: up / warn / down, as the displays decide it."""
    seen = flux('from(bucket:%s) |> range(start:-24h) |> filter(fn:(r)=> r._measurement=="node_health" and '
                'r._field=="load1") |> last() |> map(fn:(r)=>({node:r.node, t:int(v:r._time) / 1000000000})) '
                '|> group() |> keep(columns:["node","t"])' % b(BUCKET))
    flags = flux('from(bucket:%s) |> range(start:-15m) |> filter(fn:(r)=> r._measurement=="node_health" and '
                 '(r._field=="undervolt_now" or r._field=="throttled_now" or r._field=="temp_c")) |> last() '
                 '|> map(fn:(r)=>({node:r.node, f:r._field, v:float(v:r._value)})) |> group() '
                 '|> keep(columns:["node","f","v"])' % b(BUCKET))
    f = {}
    for r in flags:
        f.setdefault(r["node"], {})[r["f"]] = float(r["v"])
    out = []
    for r in sorted(seen, key=lambda r: r["node"]):
        node, h, age = r["node"], f.get(r["node"], {}), max(0, int(now - int(r["t"])))
        why = []
        if h.get("undervolt_now"):
            why.append("undervoltage")
        if h.get("throttled_now"):
            why.append("CPU throttled")
        if h.get("temp_c", 0) > HOT_C:
            why.append("running hot")
        status = "down" if age > SILENT_S else "warn" if why else "up"
        out.append({"node": node, "status": status, "age_s": age,
                    "why": "silent for %s" % ago(age) if status == "down" else ", ".join(why)})
    return out


def band(kind, f, age):
    if age > STALE_S:
        return "stale"
    lo, hi = RANGES[kind]
    return "cold" if f < lo else "hot" if f > hi else "good"


def locations(now):
    """Latest reading per location (last 6 h, as the displays): water and air in °F/°C, humidity, other percentages."""
    rows = flux('from(bucket:%s) |> range(start:-6h) |> filter(fn:(r)=> r._measurement!="node_health" and '
                '(r._field=="temp_f" or r._field=="temp_c" or r._field=="humidity" or r._field=~/_pct$/)) |> last() '
                '|> map(fn:(r)=>({loc:r.location, node:r.node, m:r._measurement, f:r._field, v:float(v:r._value), '
                't:int(v:r._time) / 1000000000})) |> group() |> keep(columns:["loc","node","m","f","v","t"])' % b(BUCKET))
    locs = {}
    for r in rows:
        name = r.get("loc") or "(no location)"
        loc = locs.setdefault(name, {"location": name, "nodes": set()})
        loc["nodes"].add(r.get("node") or "")
        m, field, v, t = r["m"], r["f"], round(float(r["v"]), 1), int(r["t"])
        if m in ("water", "air"):
            slot = loc.setdefault(m, {"t": 0})
            slot[{"temp_f": "f", "temp_c": "c", "humidity": "humidity"}.get(field, field)] = v
            slot["t"] = max(slot["t"], t)
        else:
            loc.setdefault("other", []).append({"kind": m, "field": field, "value": v, "age_s": max(0, int(now - t))})
    out = []
    for name in sorted(locs):
        loc = locs[name]
        loc["nodes"] = sorted(n for n in loc["nodes"] if n)
        for kind in ("water", "air"):
            slot = loc.get(kind)
            if slot:
                age = max(0, int(now - slot.pop("t")))
                slot["age_s"] = age
                slot["band"] = band(kind, slot["f"], age) if "f" in slot else "stale" if age > STALE_S else "good"
        out.append(loc)
    return out


def summary():
    now = time.time()
    data = {"v": 1, "time": int(now), "hub": {"id": E("HUB_ID", ""), "name": E("HUB_NAME", "")},
            "ranges": RANGES, "stale_after_s": STALE_S, "silent_after_s": SILENT_S}
    data["collectors"], data["locations"] = collectors(now), locations(now)
    bad, warn = [], []
    for c in data["collectors"]:
        if c["status"] == "down":
            bad.append("%s %s" % (c["node"], c["why"]))
        elif c["status"] == "warn":
            warn.append("%s: %s" % (c["node"], c["why"]))
    for loc in data["locations"]:
        w = loc.get("water")
        if w and w["band"] in ("cold", "hot") and "f" in w:
            bad.append("%s water %.1f°F %s" % (loc["location"], w["f"], w["band"]))
        for kind in ("water", "air"):
            s = loc.get(kind)
            if s and s["band"] == "stale":
                warn.append("%s %s reading %s old" % (loc["location"], kind, ago(s["age_s"])))
    data["status"] = {"level": "bad" if bad else "warn" if warn else "ok", "problems": bad + warn}
    return data


_lock, _cache = threading.Lock(), {"at": 0, "data": None}


def cached_summary():
    with _lock:
        if not _cache["data"] or time.time() - _cache["at"] > 5:
            _cache.update(at=time.time(), data=summary())
        return _cache["data"]


# ------------------------------------------------------------------------------------------------ paired phones
_dev_lock = threading.Lock()
_seen = {"dirty": False, "flushed": 0.0}


def load_devices():
    try:
        with open(DEVICES, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_devices(devs):
    os.makedirs(DATA, exist_ok=True)
    tmp = DEVICES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devs, f, indent=1)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, DEVICES)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def device_for(token):
    """The paired device this token belongs to, or None. Compares hashes in constant time."""
    if not token:
        return None
    d = digest(token)
    with _dev_lock:
        devs = load_devices()
        match = None
        for dev in devs:
            if hmac.compare_digest(dev["hash"], d):
                match = dev
        if match:
            now = int(time.time())
            if now - match.get("last_seen", 0) > 60:
                match["last_seen"] = now
                _seen["dirty"] = True
            if _seen["dirty"] and time.time() - _seen["flushed"] > SEEN_FLUSH_S:
                save_devices(devs)
                _seen.update(dirty=False, flushed=time.time())
        return match


HOME_URL = re.compile(r"^http://[A-Za-z0-9.-]{1,253}:\d{1,5}$")


def default_home():
    host = E("WIDGET_ADDRESS") or E("HUB_ADDRESS") or E("HUB_DETECTED_ADDRESS") or "this-host"
    return "http://%s:%s" % (host, E("WIDGET_PUBLIC_PORT", str(PORT)))


def remote_url():
    """Away-from-home address: set by hand (WIDGET_REMOTE_URL), else the hub's Tailscale address setup.sh found."""
    return (E("WIDGET_REMOTE_URL") or E("WIDGET_DETECTED_REMOTE_URL") or "").rstrip("/")


def pair_link(token, home=None):
    q = {"v": "1", "id": E("HUB_ID", ""), "n": E("HUB_NAME", ""), "u": home or default_home(), "t": token}
    if remote_url():
        q["r"] = remote_url()
    return "tankwatch://pair?" + urllib.parse.urlencode(q)


def pair_device(name, home=None):
    """Pair a new phone. Returns (its public record, its pairing link). The token exists only in the link."""
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("Give the phone a name")
    if home is not None and not HOME_URL.match(home):
        raise ValueError("The home address must look like http://192.168.1.10:8089")
    token = secrets.token_urlsafe(24)
    with _dev_lock:
        devs = load_devices()
        dev = {"id": secrets.token_hex(4), "name": name, "hash": digest(token), "created": int(time.time()), "last_seen": 0}
        devs.append(dev)
        save_devices(devs)
    return public(dev), pair_link(token, home)


def public(dev):
    return {k: dev.get(k) for k in ("id", "name", "created", "last_seen")}


def list_devices():
    return [public(d) for d in load_devices()]


def revoke_device(dev_id):
    with _dev_lock:
        devs = load_devices()
        keep = [d for d in devs if d["id"] != dev_id]
        if len(keep) == len(devs):
            return False
        save_devices(keep)
    return True


def cli(args):
    if args[:1] == ["pair"] and len(args) == 2 and args[1].strip():
        dev, link = pair_device(args[1])
        print("Paired %s (id %s). Open this link on the phone, or paste it into the TankWatch app:" % (dev["name"], dev["id"]))
        print(link)
        print("The link holds the phone's token: don't share it. It isn't shown again; pair again if you lose it.")
        return 0
    if args == ["list"]:
        devs = list_devices()
        if not devs:
            print("No phones paired yet.")
        for d in devs:
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["last_seen"])) if d.get("last_seen") else "never"
            print("%s  %-40s paired %s, last seen %s" % (d["id"], d["name"],
                                                         time.strftime("%Y-%m-%d", time.localtime(d["created"])), seen))
        return 0
    if args[:1] == ["revoke"] and len(args) == 2:
        if not revoke_device(args[1]):
            print("No paired phone with id %s (see: list)" % args[1])
            return 1
        print("Revoked %s: that phone's widget stops working within a few seconds." % args[1])
        return 0
    print("usage: widget.py [pair NAME | list | revoke ID]   (no arguments: run the service)")
    return 2


# ------------------------------------------------------------------------------------------------ web
_fails, _fails_lock = {}, threading.Lock()


def _nets(spec):
    out = []
    for part in spec.split(","):
        try:
            out.append(ipaddress.ip_network(part.strip(), strict=False))
        except ValueError:
            if part.strip():
                log.warning("WIDGET_TRUSTED_PROXIES: ignoring %r", part)
    return out


# A proxy on the hub itself (Tailscale Funnel, Caddy, nginx) reaches the container from loopback or Docker's own
# network. Only for those is X-Forwarded-For believed, so the wrong-token lockout hits the real visitor, not
# every phone behind the proxy.
TRUSTED_PROXIES = _nets(E("WIDGET_TRUSTED_PROXIES", "127.0.0.0/8,::1/128,172.16.0.0/12"))


def client_ip(peer, forwarded):
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if forwarded and any(ip in n for n in TRUSTED_PROXIES):
        last = forwarded.split(",")[-1].strip()          # the hop our own proxy added
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass
    return peer


def locked_out(addr):
    with _fails_lock:
        t = [x for x in _fails.get(addr, []) if time.time() - x < FAIL_WINDOW_S]
        _fails[addr] = t
        return len(t) >= MAX_FAILS


def failed(addr):
    with _fails_lock:
        _fails.setdefault(addr, []).append(time.time())


class Handler(BaseHTTPRequestHandler):
    server_version = "TankWatchWidget"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.client_address[0], fmt % args)

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def not_found(self):
        self.send(404, {"error": "not found"})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self.send(200, b"ok\n", "text/plain")
        if path not in ("/v1/info", "/v1/summary"):
            return self.not_found()
        addr = client_ip(self.client_address[0], self.headers.get("X-Forwarded-For"))
        if locked_out(addr):
            return self.send(429, {"error": "too many wrong tokens; try again in 10 minutes"})
        auth = self.headers.get("Authorization") or ""
        dev = device_for(auth[7:].strip()) if auth.startswith("Bearer ") else None
        if not dev:
            if auth:
                failed(addr)
                log.warning("unknown widget token from %s", addr)
            return self.not_found()
        try:
            if path == "/v1/info":
                return self.send(200, {"v": 1, "hub": {"id": E("HUB_ID", ""), "name": E("HUB_NAME", "")},
                                       "ranges": RANGES, "device": dev["name"]})
            return self.send(200, cached_summary())
        except Exception as e:
            log.warning("summary failed: %s", e)
            return self.send(503, {"error": "InfluxDB didn't answer (%s)" % type(e).__name__})

    def do_POST(self):
        self.not_found()

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_POST


# ------------------------------------------------------------------------------------------------ management
# A second listener for the admin page only: pair, list and revoke phones. It's on WIDGET_MANAGE_PORT (8099),
# which hub/docker-compose.yml never publishes, so it's reachable only inside the hub's Docker network, and it
# also needs WIDGET_ADMIN_TOKEN (from hub/.env, shared with the admin container). Without that token it's off.
MANAGE_PORT = int(E("WIDGET_MANAGE_PORT", "8099"))
ADMIN_TOKEN = E("WIDGET_ADMIN_TOKEN", "")


class ManageHandler(Handler):
    server_version = "TankWatchWidgetManage"

    def allowed(self):
        auth = self.headers.get("Authorization") or ""
        given = auth[7:].strip() if auth.startswith("Bearer ") else ""
        return bool(ADMIN_TOKEN) and bool(given) and hmac.compare_digest(given.encode(), ADMIN_TOKEN.encode())

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4096:
            raise ValueError("too long")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if self.path == "/healthz":
            return self.send(200, b"ok\n", "text/plain")
        if not self.allowed():
            return self.not_found()
        if self.path == "/manage/devices":
            return self.send(200, {"devices": list_devices(), "remote": remote_url(), "home": default_home()})
        self.not_found()

    def do_POST(self):
        if not self.allowed():
            return self.not_found()
        try:
            b = self.body()
            if self.path == "/manage/pair":
                dev, link = pair_device(b.get("name"), b.get("home") or None)
                log.info("paired %s (%s)", dev["name"], dev["id"])
                return self.send(200, {"device": dev, "link": link})
            if self.path == "/manage/revoke":
                ok = revoke_device(str(b.get("id") or ""))
                if ok:
                    log.info("revoked %s", b.get("id"))
                return self.send(200 if ok else 404, {"ok": ok})
        except (ValueError, TypeError) as e:
            return self.send(400, {"error": str(e)})
        self.not_found()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))   # as the container's first process, stop promptly
    if not READ_TOKEN:
        log.warning("INFLUX_READ_TOKEN is empty: run hub/setup.sh first")
    log.info("TankWatch widget service on port %d, reading %s bucket %s, %d phone(s) paired",
             PORT, INFLUX, BUCKET, len(load_devices()))
    if ADMIN_TOKEN:
        threading.Thread(target=ThreadingHTTPServer(("", MANAGE_PORT), ManageHandler).serve_forever, daemon=True).start()
        log.info("pairing from the admin page enabled (internal port %d)", MANAGE_PORT)
    else:
        log.info("WIDGET_ADMIN_TOKEN not set: pair phones from the command line (run hub/setup.sh to enable the admin page)")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
