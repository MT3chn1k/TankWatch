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
- [ ] Alerts (Grafana alerting to email / phone) with sensible defaults per sensor
- [ ] pH, TDS, soil moisture, level sensors
- [ ] LED status display (Pimoroni Galactic Unicorn) showing every node at a glance
- [ ] Network traffic mapping per node (NetFlow)
- [ ] Automated nightly backups of every node and the hub, with monthly archives
- [ ] Integrations: smart lighting, wearables

## License

MIT. See [LICENSE](LICENSE).
