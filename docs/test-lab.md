# The test lab

A whole TankWatch install on one computer, in Docker: a hub, four "data Pis" with realistic synthetic sensors,
and two "display Pis". Use it to try TankWatch before buying hardware, to test a change before it goes near your
real tanks, or to show someone how it works.

Every device joins the way a real Pi does, **with a join code and discovery**, so the lab tests the real setup
path, not a shortcut.

| Machine | Plays the part of | What's on it |
|---|---|---|
| hub | the central Pi | InfluxDB, Grafana and the discovery beacon, set up by the real `hub/setup.sh` |
| hub-pi | the collector on the hub machine | its own health only, so the hub gets a status light |
| livingroom-pi | a data Pi | a cichlid tank and the living room (temperature, humidity) |
| upstairs-pi | a data Pi | a 75-gallon tank and a fiddle-leaf fig (soil moisture) |
| kitchen-pi | a data Pi **given a wrong hub address on purpose** | a cat feeder (food level) and the kitchen. It has to find the hub by itself |
| display-mini | a display Pi | a virtual Unicorn HAT Mini, at http://localhost:8090 |
| display-sign | a display Pi | **the sign's real `main.py`, unchanged**, on an emulated Galactic Unicorn, at http://localhost:8091 |

## Running it

You need Docker (Docker Desktop on Windows or Mac) and Python 3.

```sh
cd tankwatch/lab
./start.sh          # sets up the lab hub and starts everything (the first run downloads and builds for a few minutes)
python check.py     # after a minute or two: checks every part and prints PASS / FAIL
./stop.sh           # stop it; ./stop.sh --wipe also deletes the lab hub's data
```

On Windows, run `start.sh` and `stop.sh` from Git Bash.

`start.sh` keeps the lab hub in `lab/run/hub/`, a private copy, so it never touches a real hub's settings in
`hub/.env`. The lab hub uses the same ports as a real one (3000, 8086, 8087), so stop one before starting the other
on the same machine.

## What check.py verifies

1. All four collectors are reporting through their join codes.
2. Every kind of synthetic reading arrives: two tanks, two rooms, a plant, a feeder.
3. **kitchen-pi found the hub by itself.** It starts pointed at an address where no hub is. After 30 seconds of
   failures (3 minutes on a real Pi) it searches the network for its hub's id, switches to it, and sends the
   readings it buffered meanwhile.
4. Both display Pis are drawing.
5. Grafana and the beacon answer.

A real run:

```
PASS  collector kitchen-pi reporting
PASS  kitchen-pi found the hub by itself   hub Bx6SuuwzcV73 moved: http://10.254.254.254:8086 -> http://172.18.0.1:8086; switching
PASS  virtual Unicorn HAT Mini drawing (17x7)      40 pixels lit
PASS  virtual status sign drawing (53x11)          99 pixels lit
...
15 of 15 checks passed
```

## The synthetic sensors

`type: synthetic` (in [node/sensors/synthetic.py](../node/sensors/synthetic.py)) makes realistic readings from
the clock: a tank heater cycling with a daily water change at 17:00, a room warming through the day, a plant drying
out over three days and being watered, a feeder emptying at three feeds a day and refilled every five days.
Because they follow the clock, restarting a collector carries on the same curves. Use them for demos, or to try
dashboards and alerts.

## Mixing in real machines

The lab's devices are ordinary TankWatch devices, so physical machines can join in:

- **A real Pi as a collector of the lab hub:** run `node/setup.sh` on the Pi with the lab's collector join code
  (`lab/run/hub/setup.sh codes`).
- **A real display Pi:** give it the lab's display join code.
- **A real hub, virtual collectors:** start the lab's collectors and displays against your real hub by putting
  its join codes in `lab/.env` (`COLLECTOR_CODE`, `DISPLAY_CODE`, `STALE_COLLECTOR_CODE`) and running
  `docker compose up -d` in `lab/`.

## Testing the collector wizard without a Pi

The wizard can run in a throwaway Debian container on the lab's network. Fake DS18B20 probes are just folders
with a `w1_slave` file, and `W1_DEVICES` points the wizard and the collector at them:

```sh
mkdir -p fakew1/28-0000aaaa1111
printf 'aa : crc=57 YES\naa t=24563\n' > fakew1/28-0000aaaa1111/w1_slave
docker run --rm -it --network tw-lab-hub_default -e W1_DEVICES=/fakew1 \
  -v "$PWD/node:/node" -v "$PWD/fakew1:/fakew1:ro" -w /node debian:bookworm-slim \
  bash -c "apt-get -qq update && apt-get -qq install -y python3 curl && ./setup.sh --dry-run"
```
