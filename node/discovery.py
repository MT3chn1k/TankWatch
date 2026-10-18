"""Join codes and hub discovery, shared by collectors, displays and the setup wizard. Standard library only.

A join code (printed by hub/setup.sh) is "tw1." + base64url JSON: hub id, InfluxDB URL, org, bucket,
role ("collector" or "display") and a token: write-only for collectors, read-only for displays.

Discovery finds a hub by its beacon (hub port 8087, /tankwatch.json), trying in order: addresses we already
know, the names tankwatch-hub.local and tankwatch-hub, then every address on this machine's local /24
networks. With a hub id, only that hub counts, so a second TankWatch hub on the network is never picked up
by mistake.
"""
import base64, concurrent.futures, json, socket, urllib.parse, urllib.request

BEACON_PORT = 8087
NAMES = ("tankwatch-hub.local", "tankwatch-hub")


def decode_join(code):
    code = "".join(code.split())
    if not code.startswith("tw1."):
        raise ValueError("that isn't a TankWatch join code (they start with tw1.)")
    raw = code[4:] + "=" * (-len(code[4:]) % 4)
    try:
        d = json.loads(base64.urlsafe_b64decode(raw))
        return {"id": d["id"], "url": d["u"], "org": d["o"], "bucket": d["b"], "role": d["r"], "token": d["t"]}
    except Exception:
        raise ValueError("that join code is damaged or incomplete; copy it again from the hub (./setup.sh codes)")


def beacon(host, timeout=1.0):
    """The hub's beacon at host, or None."""
    try:
        with urllib.request.urlopen("http://%s:%d/tankwatch.json" % (host, BEACON_PORT), timeout=timeout) as r:
            d = json.loads(r.read(4096))
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("tankwatch") != "hub":
        return None
    d["host"] = host
    d["url"] = "http://%s:%d" % (host, int(d.get("influx_port", 8086)))
    return d


def local_ipv4s():
    ips = set()
    try:  # the address used to reach the outside world; connect() on UDP sends nothing
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127.") and not i.startswith("169.254."))


def host_of(url):
    return urllib.parse.urlparse(url).hostname or ""


def find_hubs(hub_id=None, hints=(), scan=True, timeout=0.8):
    """Hubs found, nearest guesses first. Each is the beacon dict plus "host" and "url"."""
    found, seen = [], set()

    def keep(d):
        if d and d["host"] not in seen and (hub_id is None or d.get("id") == hub_id):
            seen.add(d["host"])
            found.append(d)

    for h in list(hints) + list(NAMES):
        if h:
            keep(beacon(h, timeout=1.5))
    if found or not scan:
        return found
    hosts = []
    for ip in local_ipv4s():
        prefix = ip.rsplit(".", 1)[0]
        hosts += ["%s.%d" % (prefix, n) for n in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        for d in pool.map(lambda h: beacon(h, timeout), hosts):
            keep(d)
    return found
