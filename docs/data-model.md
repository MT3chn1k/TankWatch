# What's stored, and how to query it

Everything goes into one InfluxDB bucket, `sensors` (org `tankwatch`). Each reading is a **measurement**
(what kind of thing), **tags** (which one, used for filtering), and **fields** (the numbers).

## Tags on every reading

| Tag | Comes from | Example |
|---|---|---|
| `node` | `node:` in the collector's `tankwatch.yaml` (setup.sh asks; default the Pi's host name) | `kitchen-pi` |
| `location` | `location:` for that sensor in `tankwatch.yaml` | `75-gallon` |
| `sensor` | The sensor type | `ds18b20`, `dht11` |

Anything under `tags:` for a sensor in `tankwatch.yaml` is added too.

## Measurements

| Measurement | From | Fields | Extra tags |
|---|---|---|---|
| `water` | `ds18b20` | `temp_c`, `temp_f` | `probe` (the probe's serial), `probe_name` |
| `air` | `dht` | `temp_c`, `temp_f`, `humidity` (%) | |
| `soil` | `synthetic` (plant); future soil sensors | `moisture_pct` | |
| `level` | `synthetic` (feeder); future level sensors | `level_pct` | |
| `node_health` | `node_health` | `temp_c`, `temp_f` (CPU), `load1`, `mem_used_pct`, `disk_used_pct`; on a Raspberry Pi also `undervolt_now`, `throttled_now`, `freqcap_now`, `templimit_now` and their `*_occurred` versions (0/1), `throttled_raw`, `core_v`, and `ext5v_v` (Pi 5) | |

Temperatures are stored in both °C and °F, so dashboards and alerts never convert.

## Example queries (Flux)

Latest water temperature per location, in °F:

```flux
from(bucket: "sensors")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "water" and r._field == "temp_f")
  |> group(columns: ["location"])
  |> last()
```

Collectors that haven't reported in the last 90 seconds. The status sign uses this rule:

```flux
from(bucket: "sensors")
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "node_health" and r._field == "load1")
  |> group(columns: ["node"])
  |> last()
  |> filter(fn: (r) => uint(v: now()) - uint(v: r._time) > uint(v: 90s))
```

Use the read-only token (`INFLUX_READ_TOKEN` in `hub/.env`) for anything that only needs to look.
