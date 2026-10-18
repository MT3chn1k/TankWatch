#!/usr/bin/env python3
"""Generates the Grafana dashboards in hub/grafana/dashboards/. Edit here and re-run rather than hand-editing the JSON:
    python hub/grafana/make_dashboards.py
"""
import json, os

DS = {"type": "influxdb", "uid": "tankwatch-influx"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")
_id = 0


def q(flux):
    return [{"refId": "A", "datasource": DS, "query": flux}]


def panel(kind, title, x, y, w, h, flux, unit=None, **extra):
    global _id
    _id += 1
    p = {"id": _id, "type": kind, "title": title, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": q(flux), "fieldConfig": {"defaults": {}, "overrides": []}, "options": {}}
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if kind == "timeseries":
        p["fieldConfig"]["defaults"]["custom"] = {"lineWidth": 2, "spanNulls": 300000, "showPoints": "never"}
        p["options"] = {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["last", "min", "max"]},
                        "tooltip": {"mode": "multi"}}
    if kind == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "area",
                        "textMode": "value_and_name"}
    p.update(extra)
    return p


def tag_var(name, tag, label, measurement=None):
    pred = ', predicate: (r) => r._measurement == "%s"' % measurement if measurement else ""
    return {"name": name, "label": label, "type": "query", "datasource": DS, "multi": True, "includeAll": True,
            "current": {"selected": True, "text": "All", "value": "$__all"}, "refresh": 2, "sort": 1,
            "query": 'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: v.defaultBucket, tag: "%s"%s, start: -30d)'
                     % (tag, pred)}


UNIT_VAR = {"name": "unit", "label": "Units", "type": "custom", "query": "°F : temp_f,°C : temp_c",
            "current": {"text": "°F", "value": "temp_f"},
            "options": [{"text": "°F", "value": "temp_f", "selected": True}, {"text": "°C", "value": "temp_c", "selected": False}]}

BASE = 'from(bucket: v.defaultBucket)\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'


def sensors_dashboard():
    sel = '  |> filter(fn: (r) => contains(value: r.location, set: ${location:json}))\n'
    label = ('  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: r.location + " " + r._measurement'
             ' + (if exists r.probe_name and r.probe_name != "" then " (" + r.probe_name + ")" else "")}))\n'
             '  |> group(columns: ["_field"])\n')
    win = '  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n'
    temp = BASE + '  |> filter(fn: (r) => r._measurement != "node_health" and r._field == "${unit}")\n' + sel + win + label
    hum = BASE + '  |> filter(fn: (r) => r._field == "humidity")\n' + sel + win + label
    latest = (BASE.replace("v.timeRangeStart", "-1h") + '  |> filter(fn: (r) => r._measurement != "node_health" and r._field == "${unit}")\n'
              + sel + '  |> last()\n' + label)
    panels = [
        panel("stat", "Now", 0, 0, 24, 5, latest, fieldConfig={"defaults": {"decimals": 1, "unit": "suffix:°",
              "color": {"mode": "fixed", "fixedColor": "blue"}}, "overrides": []}),
        panel("timeseries", "Temperature", 0, 5, 24, 10, temp, unit="suffix:°"),
        panel("timeseries", "Humidity", 0, 15, 24, 8, hum, unit="percent"),
    ]
    return {"uid": "tankwatch-sensors", "title": "TankWatch – Sensors", "tags": ["tankwatch"], "timezone": "browser",
            "refresh": "1m", "time": {"from": "now-24h", "to": "now"}, "schemaVersion": 39, "panels": panels,
            "templating": {"list": [tag_var("location", "location", "Location"), UNIT_VAR]}}


def health_dashboard():
    base = BASE + '  |> filter(fn: (r) => r._measurement == "node_health" and contains(value: r.node, set: ${node:json}))\n'
    by_node = '  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: r.node}))\n  |> group(columns: ["_field"])\n'

    def series(field, fn="mean"):
        return (base + '  |> filter(fn: (r) => r._field == "%s")\n' % field
                + '  |> aggregateWindow(every: v.windowPeriod, fn: %s, createEmpty: false)\n' % fn + by_node)

    def latest(field, fn="last"):
        return base.replace("v.timeRangeStart", "-10m") + '  |> filter(fn: (r) => r._field == "%s")\n  |> %s()\n' % (field, fn) + by_node

    red_at = lambda v: {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": v}]}
    temp_field = "${unit}"
    panels = [
        # Same rule as the status sign: DOWN when a collector hasn't reported for 90 s. Looks back 24 h so a
        # collector that has died stays on the board as DOWN instead of dropping off it.
        panel("stat", "Reporting now (silent 90 s = DOWN)", 0, 0, 8, 5,
              base.replace("v.timeRangeStart", "-24h") + '  |> filter(fn: (r) => r._field == "load1")\n  |> last()\n'
              + '  |> map(fn: (r) => ({_time: r._time, _field: r.node,\n'
              + '      _value: if uint(v: now()) - uint(v: r._time) <= uint(v: 90s) then 1 else 0}))\n  |> group(columns: ["_field"])\n',
              fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {"1": {"text": "UP"}, "0": {"text": "DOWN"}}}],
                                        "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None},
                                                                                     {"color": "green", "value": 1}]}},
                           "overrides": []}),
        panel("stat", "Undervolt now", 8, 0, 8, 5, latest("undervolt_now", "max"),
              fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "OK"}, "1": {"text": "UNDERVOLT"}}}],
                                        "thresholds": red_at(1)}, "overrides": []}),
        panel("stat", "Throttled now", 16, 0, 8, 5, latest("throttled_now", "max"),
              fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "OK"}, "1": {"text": "THROTTLED"}}}],
                                        "thresholds": red_at(1)}, "overrides": []}),
        panel("timeseries", "CPU temperature", 0, 5, 12, 11, series(temp_field), unit="suffix:°"),
        panel("timeseries", "Load (1 min)", 12, 5, 12, 11, series("load1")),
        panel("timeseries", "Memory used", 0, 16, 12, 11, series("mem_used_pct"), unit="percent"),
        panel("timeseries", "Disk used", 12, 16, 12, 11, series("disk_used_pct", "last"), unit="percent"),
        panel("timeseries", "Undervolt / throttle events", 0, 27, 24, 9,
              base + '  |> filter(fn: (r) => r._field == "undervolt_now" or r._field == "throttled_now")\n'
              + '  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)\n'
              + '  |> map(fn: (r) => ({_time: r._time, _value: r._value, _field: r.node + " " + r._field}))\n  |> group(columns: ["_field"])\n'),
    ]
    # collectors that had events sort to the top of the legend, so they're never the ones cut off
    panels[-1]["options"]["legend"].update({"calcs": ["max", "last"], "sortBy": "Max", "sortDesc": True})
    return {"uid": "tankwatch-health", "title": "TankWatch – Node health", "tags": ["tankwatch"], "timezone": "browser",
            "refresh": "30s", "time": {"from": "now-24h", "to": "now"}, "schemaVersion": 39, "panels": panels,
            "templating": {"list": [tag_var("node", "node", "Node", "node_health"), UNIT_VAR]}}


if __name__ == "__main__":
    for name, d in (("sensors", sensors_dashboard()), ("node-health", health_dashboard())):
        with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)
        print("wrote", name + ".json")
