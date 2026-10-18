#!/usr/bin/env python3
"""Check the TankWatch lab end to end and print PASS / FAIL for each part. Run it a minute or two after
./start.sh (the kitchen-pi rediscovery test needs about a minute).   python lab/check.py"""
import csv, io, json, os, subprocess, sys, urllib.request

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

print("\n%d of %d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
