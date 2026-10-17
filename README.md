# TankWatch

**Tracking anything you can buy an open sensor for.**

TankWatch started as a way to watch three fish tanks with Raspberry Pis. It works for anything a cheap,
open sensor can measure: aquariums, house plants, a pet feeder's food level, a room, a garage freezer.
You get the same kind of live dashboards and history that commercial aquarium controllers charge hundreds
of dollars for, on hardware you already own, with no subscription and no cloud account.

```
 sensor Pis (nodes)                          hub (one Pi 5, or any Linux box)
 ┌──────────────────────┐                     ┌──────────────────────────────┐
 │ tankwatch-node       │   readings, every   │ InfluxDB  ← stores history   │
 │  • DS18B20 water °F  │ ──────────────────► │ Grafana   ← dashboards       │
 │  • DHT11 air/humidity│   30–60 s (HTTP)    │                              │
 │  • the Pi's health   │                     │ both in Docker               │
 └──────────────────────┘                     └──────────────────────────────┘
```

- **Everything runs in Docker.** One command sets up the hub; one command starts each sensor node.
- **Sensors are plug-ins.** Each node lists its sensors in a short `config.yaml`. Adding a new kind of
  sensor is one small Python file; see [docs/adding-a-sensor.md](docs/adding-a-sensor.md).
- **Built for reliability.** Nodes keep readings in memory while the hub is unreachable and send them when it
  comes back. Every node also reports its own health (CPU temperature, Raspberry Pi undervolt and throttle
  warnings, memory, disk), so you know when a sensor box is the problem, not the tank.
- **Least-privilege tokens.** Nodes get a write-only token; Grafana gets a read-only one. A lost sensor Pi
  can't read or delete your history.
- **°F or °C.** Every temperature is stored in both; dashboards have a units switch.
- **A status sign that tells you when a collector is down.** You don't have to open a dashboard to know
  something's wrong. See below.

## The status sign: alerting you can see from across the room

A dashboard only helps if you look at it. TankWatch drives an inexpensive LED matrix sign (Pimoroni Galactic
Unicorn) that sits on a shelf and shows every collector's state by colour:

| Colour | Meaning |
|---|---|
| 🟢 Green | The collector is reporting normally |
| 🟡 Amber | It's reporting, but something's wrong: undervoltage, CPU throttling, or running hot |
| 🔴 Red | **The collector has gone silent.** No report for 90 seconds. It has crashed, lost power, or dropped off the network |

The sign reads straight from the hub's database with its own read-only token. If the hub itself stops
answering, the sign falls back to checking each Pi directly over the network. That way a dead hub can't
make every collector look healthy. Between alerts it rotates through the latest readings (water and air
temperature, humidity), so it earns its shelf space.

This matters most for the failure people don't think about. When a sensor box dies, the tank is fine, but
you've stopped watching it. Without the sign, you find out days later from a gap in a graph. With it, you
find out the next time you walk past.

Setup, buttons and the styles it can show (including a Road Rash race against your collectors) are in
[sign/README.md](sign/README.md). Which collectors and readings it shows is one small `config.json`.

## Quick start

### 1. The hub (Raspberry Pi 5 recommended, or any 64-bit Linux machine with Docker)

```sh
git clone https://github.com/<you>/tankwatch.git
cd tankwatch/hub
./setup.sh
```

`setup.sh` creates random passwords and tokens in `hub/.env`, starts InfluxDB and Grafana, and prints the
lines each sensor node needs. Open Grafana at `http://<hub-ip>:3000`.

### 2. A sensor node (any Raspberry Pi with Docker)

```sh
cd tankwatch/node
cp .env.example .env                 # paste the lines setup.sh printed
cp config.example.yaml config.yaml   # list this node's sensors
nano docker-compose.yml              # uncomment the hardware lines for your sensors
docker compose up -d --build
docker logs -f tankwatch-node        # watch the readings go out
```

No sensors wired yet? Use `type: mock` in `config.yaml` to send fake readings and see the dashboards work.

Prefer no Docker on the node? See [docs/install-node.md](docs/install-node.md).

## Supported sensors

| `type:` | What it measures | Hardware | Notes |
|---|---|---|---|
| `ds18b20` | Water / liquid temperature | DS18B20 waterproof probe + 4.7 kΩ resistor | Several probes can share one pin. [Wiring](docs/wiring/ds18b20-wiring.svg) |
| `dht` | Air temperature + humidity | DHT11 or DHT22 | [Wiring](docs/wiring/dht11-wiring.svg) |
| `node_health` | The Pi itself | none | CPU temp, undervolt/throttle, voltages, load, memory, disk |
| `mock` | Fake data | none | For testing |

Planned: pH and conductivity/TDS (Atlas Scientific EZO), soil moisture for plants, distance sensors for
feeder and reservoir levels, water-leak detection.

## Roadmap

- [x] Containerized hub and sensor node, plug-in sensors, store-and-forward, node health
- [x] **Status sign** (Pimoroni Galactic Unicorn): green / amber / red per collector, red when one goes silent
- [ ] Alerts (Grafana alerting to email / phone) with sensible defaults per sensor
- [ ] pH, TDS, soil moisture, level sensors
- [ ] Network traffic mapping per node (NetFlow)
- [ ] Automated nightly backups of every node and the hub, with monthly archives
- [ ] Integrations: smart lighting, wearables

## License

MIT. See [LICENSE](LICENSE).
