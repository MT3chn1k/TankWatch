#!/usr/bin/env python3
"""Small helpers for setup.sh, kept in Python so the shell script stays readable. Standard library only.

  read-hub FILE                 the hub: section of an existing tankwatch.yaml, as JSON (nothing if none)
  previous FILE KEY             an earlier answer from tankwatch.yaml, so a re-run offers it as the default:
                                "node", "probe:<serial>" (that probe's location), "dht" (11/22/n),
                                "dht-pin", "dht-location"
  join CODE                     a collector join code's hub settings, as JSON
  get JSON KEY                  one value from a JSON object
  find HUB_ID URL               the hub's address if it's found on the network (nothing if not)
  host URL                      the host name or address in a URL
  config HUB_JSON URL NAME      the top of tankwatch.yaml: node name and hub settings
"""
import json, re, sys

import discovery


def read_hub(path):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return
    m = re.search(r"(?m)^hub:\n((?:[ \t]+.*\n?)+)", text)
    if not m:
        return
    hub = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.strip().split(":", 1)
            value = value.split(" #")[0].strip()
            hub[key] = json.loads(value) if value.startswith('"') else value
    if hub.get("token"):
        print(json.dumps(hub))


def previous(path, key):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return
    if key == "node":
        m = re.search(r'(?m)^node:\s*"?([^"\n]+)"?', text)
        print(m.group(1).strip() if m else "")
        return
    for entry in re.split(r"(?m)^  - ", text)[1:]:
        loc = re.search(r"(?m)^\s+location:\s*(\S+)", entry)
        if key.startswith("probe:") and key[6:] in entry and entry.startswith("type: ds18b20"):
            print(loc.group(1) if loc else "")
            return
        if entry.startswith("type: dht"):
            model = re.search(r"model:\s*dht(\d+)", entry)
            pin = re.search(r"pin:\s*D(\d+)", entry)
            value = {"dht": model and model.group(1), "dht-pin": pin and pin.group(1),
                     "dht-location": loc and loc.group(1)}.get(key)
            if value:
                print(value)
                return
    if key == "dht":
        print("n")


def join(code):
    j = discovery.decode_join(code)
    if j["role"] != "collector":
        sys.exit("That is the DISPLAY join code. A collector needs the COLLECTOR join code.")
    print(json.dumps({k: j[k] for k in ("id", "url", "org", "bucket", "token")}))


def config(hub_json, url, name):
    h = json.loads(hub_json)
    h["url"] = url
    print("# TankWatch collector settings, written by setup.sh. Re-run setup.sh to change them.")
    print("# The hub token below is a password: keep this file private.")
    print("node: " + json.dumps(name))
    print("hub:")
    for k in ("id", "url", "org", "bucket", "token"):
        print("  %s: %s" % (k, json.dumps(h[k])))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "read-hub":
            read_hub(args[0])
        elif cmd == "previous":
            previous(*args)
        elif cmd == "join":
            join(args[0])
        elif cmd == "get":
            print(json.loads(args[0])[args[1]])
        elif cmd == "find":
            hubs = discovery.find_hubs(hub_id=args[0], hints=[discovery.host_of(args[1])])
            print(hubs[0]["url"] if hubs else "")
        elif cmd == "host":
            print(discovery.host_of(args[0]))
        elif cmd == "config":
            config(*args)
        else:
            sys.exit("unknown helper command %s" % cmd)
    except ValueError as e:
        sys.exit(str(e))
