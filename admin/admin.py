#!/usr/bin/env python3
"""TankWatch admin page: every collector at a glance, what each one reports, and adding a new sensor Pi.

Runs on the hub next to InfluxDB and Grafana (see hub/docker-compose.yml): http://<hub>:8088
It's password protected (ADMIN_PASSWORD in hub/.env, printed by hub/setup.sh) because it can show the join codes.

It only reads: queries go to InfluxDB with the read-only token, and nothing on the hub is changed. The sign
config it builds is made in your browser for you to download. The one exception is the optional phone widget
add-on: it can ask the widget service to pair or revoke a phone (see widget/widget.py). Standard library only.

Settings come from environment variables (hub/docker-compose.yml passes them from hub/.env):
  ADMIN_PASSWORD        the page's password (user name: admin)
  INFLUX_URL            where InfluxDB is (default http://influxdb:8086)
  INFLUX_ORG, INFLUX_BUCKET, INFLUX_READ_TOKEN
  NODE_WRITE_TOKEN      only to build the collector join code; never used to write
  HUB_ID, HUB_NAME      which hub this is
  HUB_ADDRESS           the address to put in join codes (hub/.env override); otherwise the address your browser
                        used to reach this page, or HUB_DETECTED_ADDRESS (what setup.sh found)
  ADMIN_PORT            default 8088
  INFLUX_PUBLIC_PORT, GRAFANA_PUBLIC_PORT   the ports other devices use (hub/.env INFLUX_PORT, GRAFANA_PORT)
  WIDGET_ADMIN_TOKEN    lets this page pair and revoke phones through the widget service (set by setup.sh)
  WIDGET_MANAGE_URL     the widget service's internal management address (default http://widget:8099)
  WIDGET_PUBLIC_PORT    the port phones use for the widget service (hub/.env WIDGET_PORT)
"""
import base64, csv, hmac, io, ipaddress, json, logging, os, re, signal, sys, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s admin: %(message)s")
log = logging.getLogger()

E = os.environ.get
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(E("ADMIN_PORT", "8088"))
INFLUX = E("INFLUX_URL", "http://influxdb:8086").rstrip("/")
GRAFANA = E("GRAFANA_URL", "http://grafana:3000").rstrip("/")
BEACON = E("BEACON_URL", "http://influxdb:8087").rstrip("/")
ORG, BUCKET = E("INFLUX_ORG", "tankwatch"), E("INFLUX_BUCKET", "sensors")
PASSWORD = E("ADMIN_PASSWORD", "")
PUBLIC = {"influx": int(E("INFLUX_PUBLIC_PORT", "8086")), "grafana": int(E("GRAFANA_PUBLIC_PORT", "3000"))}

SILENT_S, HOT_C, NEW_S = 90, 77, 3600     # same rules as the displays: silent 90 s = down; CPU over 77 °C = hot
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
          "/admin.css": ("admin.css", "text/css; charset=utf-8"),
          "/icon.png": ("icon.png", "image/png"), "/qrcode.js": ("qrcode.js", "text/javascript; charset=utf-8")}
HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


# ------------------------------------------------------------------------------------------------ InfluxDB
def flux(q, timeout=10):
    req = urllib.request.Request("%s/api/v2/query?org=%s" % (INFLUX, urllib.parse.quote(ORG)), data=q.encode(),
                                 method="POST", headers={"Authorization": "Token " + E("INFLUX_READ_TOKEN", ""),
                                                         "Content-Type": "application/vnd.flux",
                                                         "Accept": "application/csv"})
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


def b(s):
    """The bucket name, quoted for Flux (it comes from hub/.env, but quote it anyway)."""
    return json.dumps(s)


def num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def collectors():
    """Every collector heard from in the last 7 days, with its latest health readings and up/warn/down."""
    q = ('from(bucket:%s) |> range(start:-7d) |> filter(fn:(r)=> r._measurement=="node_health") |> last() '
         '|> map(fn:(r)=>({node:r.node, f:r._field, v:float(v:r._value), t:int(v:r._time) / 1000000000})) '
         '|> group() |> keep(columns:["node","f","v","t"])' % b(BUCKET))
    first = ('from(bucket:%s) |> range(start:-30d) |> filter(fn:(r)=> r._measurement=="node_health" and '
             'r._field=="load1") |> first() |> map(fn:(r)=>({node:r.node, t:int(v:r._time) / 1000000000})) '
             '|> group() |> keep(columns:["node","t"])' % b(BUCKET))
    nodes, now = {}, time.time()
    for r in flux(q):
        n = nodes.setdefault(r["node"], {"node": r["node"], "seen": 0, "health": {}})
        n["health"][r["f"]] = num(r["v"])
        n["seen"] = max(n["seen"], int(r["t"]))
    for r in flux(first):
        if r["node"] in nodes:
            nodes[r["node"]]["first_seen"] = int(r["t"])
    out = []
    for n in sorted(nodes.values(), key=lambda n: n["node"]):
        h, age = n["health"], now - n["seen"]
        why = []
        if h.get("undervolt_now"):
            why.append("undervoltage: check its power supply")
        if h.get("throttled_now"):
            why.append("CPU throttled")
        if (h.get("temp_c") or 0) > HOT_C:
            why.append("running hot")
        n["status"] = "down" if age > SILENT_S else "warn" if why else "up"
        n["why"] = "silent for %s" % ago(age) if n["status"] == "down" else ", ".join(why)
        n["new"] = n["status"] != "down" and now - n.get("first_seen", 0) < NEW_S
        out.append(n)
    return out


def sources():
    """What every collector reports (last 7 days): one row per sensor reading, with its latest values."""
    q = ('from(bucket:%s) |> range(start:-7d) |> filter(fn:(r)=> r._measurement!="node_health") |> last() '
         '|> map(fn:(r)=>({node:r.node, location:r.location, sensor:r.sensor, probe:r.probe, probe_name:r.probe_name, '
         'm:r._measurement, f:r._field, v:float(v:r._value), t:int(v:r._time) / 1000000000})) '
         '|> group() |> keep(columns:["node","location","sensor","probe","probe_name","m","f","v","t"])' % b(BUCKET))
    rows = {}
    for r in flux(q):
        key = (r.get("location") or "", r["m"], r.get("node") or "", r.get("sensor") or "", r.get("probe") or "")
        s = rows.setdefault(key, {"location": key[0], "measurement": key[1], "node": key[2], "sensor": key[3],
                                  "probe": key[4], "probe_name": r.get("probe_name") or "", "fields": {}, "t": 0})
        s["fields"][r["f"]] = num(r["v"])
        s["t"] = max(s["t"], int(r["t"]))
    return [rows[k] for k in sorted(rows)]


def reachable(url, needle):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return needle in r.read(4096)
    except Exception:
        return False


def ago(s):
    s = int(s)
    return "%d s" % s if s < 120 else "%d min" % (s // 60) if s < 7200 else "%d h" % (s // 3600) if s < 172800 \
        else "%d days" % (s // 86400)


_lock, _cache = threading.Lock(), {"at": 0, "data": None}


def overview():
    with _lock:
        if not _cache["data"] or time.time() - _cache["at"] > 5:
            data = {"time": int(time.time()), "hub": {"id": E("HUB_ID", ""), "name": E("HUB_NAME", ""),
                                                      "org": ORG, "bucket": BUCKET, "ports": PUBLIC},
                    "services": {"InfluxDB": reachable(INFLUX + "/health", b'"pass"'),
                                 "Grafana": reachable(GRAFANA + "/api/health", b'"database"'),
                                 "Discovery beacon": reachable(BEACON + "/tankwatch.json", b'"tankwatch"')},
                    "collectors": [], "sources": [], "error": ""}
            try:
                data["collectors"], data["sources"] = collectors(), sources()
            except Exception as e:
                log.warning("query failed: %s", e)
                data["error"] = "InfluxDB didn't answer the query (%s)" % type(e).__name__
            _cache.update(at=time.time(), data=data)
        return _cache["data"]


# ------------------------------------------------------------------------------------------------ join codes
def join_address(host_header):
    """The hub address to put in join codes: hub/.env HUB_ADDRESS, else the address the browser used to reach this
    page (unless that's this machine itself), else what setup.sh detected."""
    if E("HUB_ADDRESS"):
        return E("HUB_ADDRESS")
    host = (host_header or "").strip()
    host = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        ip = ipaddress.ip_address(host)
        usable = not (ip.is_loopback or ip.is_unspecified or ip.version != 4)
    except ValueError:
        usable = bool(HOSTNAME.match(host)) and host.lower() not in ("localhost", "localhost.localdomain")
    return host if usable else E("HUB_DETECTED_ADDRESS", "") or "this-host"


# ------------------------------------------------------------------------------------------------ phone widget
# The widget service (an optional add-on) keeps the paired phones. This page asks it to pair, list and revoke over
# its management port, which is only reachable inside the hub's Docker network and needs WIDGET_ADMIN_TOKEN.
# This page never sees a phone's token after showing the pairing link once.
WIDGET_MANAGE = E("WIDGET_MANAGE_URL", "http://widget:8099").rstrip("/")
WIDGET_ADMIN_TOKEN = E("WIDGET_ADMIN_TOKEN", "")
WIDGET_PUBLIC_PORT = int(E("WIDGET_PUBLIC_PORT", "8089"))


def widget_call(path, body=None):
    """(HTTP status, JSON) from the widget service's management port. Raises OSError if it isn't running."""
    req = urllib.request.Request(WIDGET_MANAGE + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + WIDGET_ADMIN_TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def widget_status(host_header):
    """What the admin page's Phone widget section shows."""
    if not WIDGET_ADMIN_TOKEN:
        return {"enabled": False, "why": "setup"}
    try:
        code, j = widget_call("/manage/devices")
    except OSError:
        return {"enabled": False, "why": "off"}
    if code != 200:
        return {"enabled": False, "why": "token"}
    return {"enabled": True, "devices": j.get("devices", []), "remote": j.get("remote", ""),
            "home": "http://%s:%d" % (join_address(host_header), WIDGET_PUBLIC_PORT)}


def join_code(role, token, address):
    d = {"v": 1, "id": E("HUB_ID", ""), "u": "http://%s:%d" % (address, PUBLIC["influx"]), "o": ORG, "b": BUCKET, "r": role, "t": token}
    raw = json.dumps(d, separators=(",", ":")).encode()
    return "tw1." + base64.urlsafe_b64encode(raw).decode().rstrip("=")


# ------------------------------------------------------------------------------------------------ web
_fails, _fails_lock = {}, threading.Lock()
MAX_FAILS, FAIL_WINDOW_S = 10, 600


def locked_out(addr):
    with _fails_lock:
        t = [x for x in _fails.get(addr, []) if time.time() - x < FAIL_WINDOW_S]
        _fails[addr] = t
        return len(t) >= MAX_FAILS


def failed(addr):
    with _fails_lock:
        _fails.setdefault(addr, []).append(time.time())


class Handler(BaseHTTPRequestHandler):
    server_version = "TankWatchAdmin"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.client_address[0], fmt % args)

    def send(self, code, body, ctype="application/json", extra=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        """True if the request carries the admin password; otherwise answers it (401 or 429) and returns False."""
        addr = self.client_address[0]
        if not PASSWORD:
            self.send(503, b"The admin page has no password yet. On the hub, run ./setup.sh again: it adds\n"
                           b"ADMIN_PASSWORD to hub/.env and restarts the admin page.\n", "text/plain; charset=utf-8")
            return False
        if locked_out(addr):
            self.send(429, b"Too many wrong passwords. Try again in 10 minutes.\n", "text/plain; charset=utf-8")
            return False
        given = ""
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Basic "):
            try:
                user, _, given = base64.b64decode(auth[6:], validate=True).decode().partition(":")
            except Exception:
                given = ""
        if given and hmac.compare_digest(given.encode(), PASSWORD.encode()):
            return True
        if auth:
            failed(addr)
            log.warning("wrong admin password from %s", addr)
        self.send(401, b"TankWatch admin: log in as admin with ADMIN_PASSWORD from hub/.env\n",
                  "text/plain; charset=utf-8", [("WWW-Authenticate", 'Basic realm="TankWatch admin", charset="UTF-8"')])
        return False

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self.send(200, b"ok\n", "text/plain")
        if not self.authorized():
            return
        try:
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(os.path.join(HERE, name), "rb") as f:
                    return self.send(200, f.read(), ctype)
            if path == "/api/overview":
                return self.send(200, overview())
            if path == "/api/widget":
                return self.send(200, widget_status(self.headers.get("Host")))
            if path == "/api/join":
                addr = join_address(self.headers.get("Host"))
                return self.send(200, {"address": addr,
                                       "collector": join_code("collector", E("NODE_WRITE_TOKEN", ""), addr),
                                       "display": join_code("display", E("INFLUX_READ_TOKEN", ""), addr)})
        except Exception as e:
            log.exception("error answering %s", path)
            return self.send(500, {"error": type(e).__name__})
        self.send(404, {"error": "not found"})

    def same_site(self):
        """Refuse requests another website could make your browser send: they need our own header and JSON, and if
        the browser says where the request came from, it must be this page."""
        if self.headers.get("X-TankWatch-Admin") != "1":
            return False
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            return urllib.parse.urlsplit(origin).netloc == (self.headers.get("Host") or "")
        return True

    def do_POST(self):
        # The only changes this page can make: pairing and revoking phones for the widget add-on.
        path = self.path.split("?", 1)[0]
        if path not in ("/api/widget/pair", "/api/widget/revoke"):
            return self.send(405, {"error": "this page only reads"}, extra=[("Allow", "GET")])
        if not self.authorized():
            return
        if not self.same_site():
            log.warning("refused a cross-site request for %s from %s", path, self.client_address[0])
            return self.send(403, {"error": "refused: not from the admin page"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if 0 < n <= 4096 else {}
            if path == "/api/widget/pair":
                home = "http://%s:%d" % (join_address(self.headers.get("Host")), WIDGET_PUBLIC_PORT)
                code, j = widget_call("/manage/pair", {"name": str(body.get("name") or ""), "home": home})
            else:
                code, j = widget_call("/manage/revoke", {"id": str(body.get("id") or "")})
            return self.send(code, j)
        except OSError:
            return self.send(503, {"error": "The phone widget service isn't running"})
        except ValueError:
            return self.send(400, {"error": "bad request"})

    def do_PUT(self):
        self.send(405, {"error": "this page only reads"}, extra=[("Allow", "GET")])

    do_DELETE = do_PATCH = do_PUT


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))   # as the container's first process, stop promptly
    if not PASSWORD:
        log.warning("ADMIN_PASSWORD is empty: the page will ask you to run hub/setup.sh again")
    elif len(PASSWORD) < 12:
        log.warning("ADMIN_PASSWORD is shorter than 12 characters")
    log.info("TankWatch admin on port %d, reading %s bucket %s", PORT, INFLUX, BUCKET)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
