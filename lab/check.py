#!/usr/bin/env python3
"""Check the TankWatch lab end to end and print PASS / FAIL for each part. Run it a minute or two after
./start.sh (the kitchen-pi rediscovery test needs about a minute).   python lab/check.py"""
import base64, csv, io, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(l.rstrip("\n").split("=", 1) for l in open(os.path.join(HERE, "run", "hub", ".env")) if "=" in l and not l.startswith("#"))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %-44s %s" % ("PASS" if ok else "FAIL", name, detail))


def flux(q):
    req = urllib.request.Request("http://localhost:8086/api/v2/query?org=" + env["INFLUX_ORG"], data=q.encode(), method="POST",
                                 headers={"Authorization": "Token " + env["INFLUX_READ_TOKEN"],
                                          "Content-Type": "application/vnd.flux", "Accept": "application/csv"})
    rows, head = [], None
    for rec in csv.reader(io.StringIO(urllib.request.urlopen(req, timeout=10).read().decode())):
        if len(rec) > 2 and rec[1] == "result":
            head = rec
        elif len(rec) > 2 and head:
            rows.append(dict(zip(head, rec)))
    return rows


def _closed(port):
    """True if nothing answers on this port from outside Docker (the widget's management port must not)."""
    import socket
    try:
        socket.create_connection(("localhost", port), timeout=2).close()
        return False
    except OSError:
        return True


def get(url):
    try:
        return urllib.request.urlopen(url, timeout=5).read()
    except Exception as e:
        return str(e).encode()


# 1. every collector reporting through its join code
recent = {r["node"] for r in flux('from(bucket:"%s") |> range(start:-2m) |> filter(fn:(r)=> r._measurement=="node_health" '
                                  'and r._field=="load1") |> group(columns:["node"]) |> last()' % env["INFLUX_BUCKET"])}
for node in ("hub-pi", "livingroom-pi", "upstairs-pi", "kitchen-pi"):
    check("collector %s reporting" % node, node in recent)

# 2. every kind of synthetic reading arriving
kinds = {(r["_measurement"], r["location"]) for r in flux(
    'from(bucket:"%s") |> range(start:-5m) |> filter(fn:(r)=> r._measurement!="node_health") '
    '|> group(columns:["_measurement","location"]) |> last()' % env["INFLUX_BUCKET"])}
for kind in (("water", "cichlid-tank"), ("water", "75-gallon"), ("air", "living-room"), ("air", "kitchen"),
             ("soil", "fiddle-leaf-fig"), ("level", "cat-feeder")):
    check("readings: %s at %s" % kind, kind in kinds)

# 3. kitchen-pi started with a dead hub address and found the hub on its own
logs = subprocess.run(["docker", "compose", "logs", "kitchen-pi"], cwd=HERE, capture_output=True, text=True).stdout
moved = [l for l in logs.splitlines() if "moved:" in l]
check("kitchen-pi found the hub by itself", bool(moved), moved[0].split("WARNING tankwatch: ")[-1] if moved else "")

# 4. displays drawing something
for name, port in (("virtual Unicorn HAT Mini", 8090), ("virtual status sign", 8091)):
    try:
        f = json.loads(get("http://localhost:%d/frame.json" % port))
        lit = sum(1 for p in f["p"] if any(p))
        check("%s drawing (%dx%d)" % (name, f["w"], f["h"]), lit > 5, "%d pixels lit" % lit)
    except Exception as e:
        check("%s drawing" % name, False, str(e)[:60])

# 5. dashboards
check("Grafana up", b'"database"' in get("http://localhost:3000/api/health"))
check("beacon answering", b'"tankwatch": "hub"' in get("http://localhost:8087/tankwatch.json"))

# 6. admin page: password required, every collector listed, a join code for this hub
auth = {"Authorization": "Basic " + base64.b64encode(("admin:" + env.get("ADMIN_PASSWORD", "")).encode()).decode()}
try:
    urllib.request.urlopen("http://localhost:8088/api/overview", timeout=5)
    check("admin page asks for its password", False, "answered without one")
except urllib.error.HTTPError as e:
    check("admin page asks for its password", e.code == 401, "HTTP %d" % e.code)
except Exception as e:
    check("admin page asks for its password", False, str(e)[:60])
try:
    o = json.loads(urllib.request.urlopen(urllib.request.Request("http://localhost:8088/api/overview", headers=auth), timeout=10).read())
    names = {c["node"] for c in o["collectors"]}
    check("admin page lists every collector", {"hub-pi", "livingroom-pi", "upstairs-pi", "kitchen-pi"} <= names, ", ".join(sorted(names)))
    j = json.loads(urllib.request.urlopen(urllib.request.Request("http://localhost:8088/api/join", headers=auth), timeout=5).read())
    sys.path.insert(0, os.path.join(HERE, "..", "node"))
    import discovery  # noqa: E402
    d = discovery.decode_join(j["collector"])
    check("admin page join code is for this hub", d["id"] == env["HUB_ID"] and d["role"] == "collector", d["url"])
except Exception as e:
    check("admin page with its password", False, str(e)[:60])

# 7. phone widget service (optional add-on): only a paired phone gets an answer, and it agrees with the admin page
def widget(path, token=None, method="GET"):
    """(HTTP status, parsed JSON or None) from the widget service."""
    req = urllib.request.Request("http://localhost:8089" + path, method=method,
                                 headers={"Authorization": "Bearer " + token} if token else {})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)[:60]


tok_file = os.path.join(HERE, "run", "widget-token")
token = open(tok_file).read().strip() if os.path.exists(tok_file) else ""
check("widget: lab phone paired", bool(token), "" if token else "no lab/run/widget-token: see start.sh output")
check("widget: no token gets 404", widget("/v1/summary")[0] == 404)
check("widget: wrong token gets 404", widget("/v1/summary", "not-a-real-token")[0] == 404)
check("widget: other paths get 404", widget("/api/join", token)[0] == 404 and widget("/", token)[0] == 404)
check("widget: writes refused", widget("/v1/summary", token, "POST")[0] == 404)
code, s = widget("/v1/summary", token)
check("widget: summary for the paired phone", code == 200 and isinstance(s, dict), "HTTP %s" % code)
if code == 200 and isinstance(s, dict):
    states = {c["node"]: c["status"] for c in s["collectors"]}
    check("widget: every collector listed", {"hub-pi", "livingroom-pi", "upstairs-pi", "kitchen-pi"} <= set(states),
          ", ".join("%s %s" % kv for kv in sorted(states.items())))
    try:   # same rules as the admin page (and the displays): statuses must agree
        admin_states = {c["node"]: c["status"] for c in o["collectors"]}
        same = all(admin_states.get(n) == st for n, st in states.items() if n in admin_states)
        check("widget: statuses match the admin page", same,
              "" if same else "widget %s vs admin %s" % (states, admin_states))
    except NameError:
        check("widget: statuses match the admin page", False, "admin page check didn't run")
    locs = {l["location"]: l for l in s["locations"]}
    check("widget: water readings per location", all("water" in locs.get(x, {}) for x in ("cichlid-tank", "75-gallon")),
          ", ".join("%s %s°F %s" % (x, locs[x]["water"].get("f"), locs[x]["water"]["band"])
                    for x in ("cichlid-tank", "75-gallon") if "water" in locs.get(x, {})))
    check("widget: air and humidity per location", all("humidity" in locs.get(x, {}).get("air", {})
                                                      for x in ("living-room", "kitchen")))
    check("widget: overall status given", s["status"]["level"] in ("ok", "warn", "bad"),
          "%s: %s" % (s["status"]["level"], "; ".join(s["status"]["problems"][:2])))

# 8. pairing a phone from the admin page: password and same-site guards, a working link, and revoking it
def admin_post(path, body, headers):
    req = urllib.request.Request("http://localhost:8088" + path, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)[:60]


ok_headers = dict(auth, **{"Content-Type": "application/json", "X-TankWatch-Admin": "1"})
check("admin pairing needs the password",
      admin_post("/api/widget/pair", {"name": "x"}, {"Content-Type": "application/json", "X-TankWatch-Admin": "1"})[0] == 401)
check("admin pairing refuses other websites",
      admin_post("/api/widget/pair", {"name": "x"}, dict(auth, **{"Content-Type": "application/json"}))[0] == 403
      and admin_post("/api/widget/pair", {"name": "x"}, dict(ok_headers, Origin="http://evil.example"))[0] == 403)
code, p = admin_post("/api/widget/pair", {"name": "check.py phone"}, ok_headers)
link = p.get("link", "") if isinstance(p, dict) else ""
check("admin page pairs a phone", code == 200 and link.startswith("tankwatch://pair?"), link[:48] + "…" if link else "HTTP %s" % code)
if link:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
    new_token, dev_id = q.get("t", [""])[0], p["device"]["id"]
    check("pairing link is for this hub", q.get("id", [""])[0] == env["HUB_ID"] and q.get("u", [""])[0].endswith(":8089"),
          q.get("u", [""])[0])
    check("the new phone gets the summary", widget("/v1/summary", new_token)[0] == 200)
    try:
        listed = json.loads(urllib.request.urlopen(urllib.request.Request("http://localhost:8088/api/widget", headers=auth), timeout=10).read())
        check("admin page lists the paired phone", any(d["id"] == dev_id for d in listed.get("devices", [])))
    except Exception as e:
        check("admin page lists the paired phone", False, str(e)[:60])
    check("admin page revokes it", admin_post("/api/widget/revoke", {"id": dev_id}, ok_headers)[0] == 200
          and widget("/v1/summary", new_token)[0] == 404)
check("pairing port isn't published", widget("/manage/devices")[0] == 404 and _closed(8099))

print("\n%d of %d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
