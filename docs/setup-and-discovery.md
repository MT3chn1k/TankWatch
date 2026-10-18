# Setup, join codes and discovery

How a new Raspberry Pi finds its way to the hub, without anyone typing IP addresses or long tokens.

## The short version

1. On the hub: `hub/setup.sh`. It prints two **join codes**.
2. On each sensor Pi: `node/setup.sh`. Paste the collector join code, answer a few questions, done.
3. On each display Pi: put the display join code in `display/.env` (see [display/README.md](../display/README.md)).

From then on, if the hub's address ever changes, collectors and displays find it again by themselves.

## The hub

The hub runs anywhere Docker runs: a Raspberry Pi 4 or 5 (64-bit OS), any Linux machine, a Windows or Mac PC
with Docker Desktop, or a NAS with a container manager. `hub/setup.sh`:

- creates random passwords and tokens in `hub/.env` (keep it private),
- starts InfluxDB (port 8086), Grafana (3000) and the discovery beacon (8087),
- **checks those ports answer on the machine's network address**, not just on the machine itself. If they don't,
  the usual cause is a firewall: Windows and macOS may need to allow Docker,
- prints the **join codes**. `./setup.sh codes` prints them again any time.

### Network setup for the hub

| Do this | Why |
|---|---|
| Give the hub a **DHCP reservation** in your router | Collectors connect faster when the address never changes. Discovery copes if it does, but a fixed address is simpler. |
| Allow ports **8086, 8087 and 3000** on the hub's firewall, for your home network | Collectors write to 8086, everything finds the hub on 8087, you browse 3000 |
| **Don't** forward those ports on your router | The hub is for your home network only. To look in from outside, use a VPN such as WireGuard or Tailscale |
| Keep the hub machine awake | A sleeping PC is a sleeping hub. Collectors buffer their readings in the meantime (up to 10,000 each, typically a day or more), so a nap loses nothing |

If `setup.sh` puts the wrong address in the join codes (a machine with several network adapters), set
`HUB_ADDRESS=` in `hub/.env` and run `./setup.sh codes` again.

## Join codes

A join code is one line starting `tw1.`. It contains everything a device needs: which hub (its id), the hub's
address, and a token.

| Code | For | Its token can |
|---|---|---|
| **Collector** join code | sensor Pis | **only write** readings. It can't read your history or delete anything. |
| **Display** join code | the status sign, Unicorn HAT Mini displays | **only read** readings |

Both codes are secrets in the way a Wi-Fi password is: share them only with your own devices. If one leaks,
delete that token in InfluxDB (`http://<hub>:8086`, Load Data, API Tokens), blank its line in `hub/.env`
(`NODE_WRITE_TOKEN=` or `INFLUX_READ_TOKEN=`), and run `./setup.sh` to make a new one. Then re-join your devices.

## Discovery: finding the hub

The hub's beacon answers `http://<hub>:8087/tankwatch.json` with a small description: that it's a TankWatch hub,
its id and its name. No tokens or passwords. A device looks for its hub in this order:

1. **The address it already knows.**
2. **The names `tankwatch-hub.local` and `tankwatch-hub`.** Raspberry Pi OS and most Linux machines announce their
   names on the network automatically, so naming your hub Pi `tankwatch-hub` makes this instant.
3. **Every address on its local network** (the /24 it's on), asking each one for the beacon. This is what finds a
   hub on a Windows PC, Mac or NAS, where name announcements don't reach Docker containers. It takes about 5 to 15 seconds.

A device only accepts **the hub whose id matches its join code**, so a second TankWatch hub on the same network
(a neighbour's, or a test lab) is never picked up by mistake.

**When it happens:** at setup (if the address in the join code doesn't answer), and whenever a collector or
display has been unable to reach the hub for 3 minutes. A collector that finds its hub at a new address
switches to it, sends the readings it buffered, and saves the new address in `tankwatch.yaml`.

**When it can't work:** guest Wi-Fi networks and some mesh systems keep devices from seeing each other, and a
strict firewall on the hub can block port 8087. Setup then asks you for the hub's address.

## The collector wizard: `node/setup.sh`

Run it on the Pi that has the sensors, from the `node` folder:

```sh
git clone https://github.com/MT3chn1k/tankwatch.git
cd tankwatch/node
./setup.sh
```

What it does, in order:

1. **Docker:** installs it if it's missing (it asks first).
2. **Hub:** asks for the collector join code, checks the hub answers, and looks for it on the network if not.
3. **Name:** for this collector in dashboards and on the sign. The default is the Pi's own name.
4. **Sensors:**
   - finds every DS18B20 probe on the 1-Wire bus, shows its current temperature, and asks where each one is,
   - if 1-Wire is switched off, offers to switch it on (that needs a reboot; run `./setup.sh` again afterwards),
   - asks whether a DHT11 or DHT22 is wired, on which GPIO, and where it is,
   - always adds `node_health`, the Pi's own health.
5. **Writes `tankwatch.yaml`** (readable only by you) and, if your sensors need hardware access,
   `docker-compose.override.yml`. You don't edit Docker files by hand.
6. **Tests every sensor once** and shows the readings, then starts the collector and shows its first log lines.

**Re-running it is safe.** It keeps the hub settings and offers your previous answers as the defaults, so adding a
probe means pressing Enter through what you had and naming the new one. Run with all defaults, it leaves the
config exactly as it was.

For scripted installs: `./setup.sh --join CODE --name NAME --yes`. `--no-docker` does everything except build and
start the container (see [install-node.md](install-node.md)); `--dry-run` only writes the config files.

## What's in tankwatch.yaml

See [node/tankwatch.example.yaml](../node/tankwatch.example.yaml). In short: the collector's name, the hub
settings from the join code, and the list of sensors with their locations. The older layout (`config.yaml` plus
`INFLUX_*` settings in `.env`) still works, so existing installs keep running.

## Trust model

TankWatch assumes **a trusted home network**. Everything travels as plain, unencrypted HTTP, so tokens and
readings are visible to any device on the same network. Don't run it on shared, guest or public Wi-Fi, and don't
open it to the internet. See [SECURITY.md](../SECURITY.md).

## What the containers can and can't do

Collectors and displays use the Pi's own network (`network_mode: host`) so discovery can scan your home network
and the collector takes the Pi's name. That would normally give a container more than it needs, so both are
locked down:

| Limit | Collector | Display (HAT Mini) | What it prevents |
|---|---|---|---|
| Runs as | the Pi user who ran `setup.sh` (usually `pi`) | root, to open the HAT's devices | the collector being root inside its container |
| Linux capabilities | none | none | capturing or forging network traffic, changing network settings, reading files it doesn't own |
| Filesystem | read-only, except its own `tankwatch.yaml` | read-only | changing its own code or leaving anything behind |
| Gaining privileges | blocked (`no-new-privileges`) | blocked | a bug turning into root access |
| Host files it can see | only the `node` folder (read-only, for disk use), its `tankwatch.yaml`, and `/sys/bus/w1` if you have probes | none | reading anything else on the Pi, including SSH keys (yours too) and password hashes: they aren't shared with it |
| Devices | `/dev/gpiomem` or `/dev/gpiochip*` only if a DHT is wired (plus the `gpio` group) | the HAT's SPI devices | |

What host networking still allows: it can reach anything on your home network that the Pi can, including services
on the Pi that only listen on `localhost`. Treat it like any program you install on the Pi.

### Known limits

- **A device on your network could pretend to be your hub.** The beacon tells anyone who asks your hub's id, so
  something on your Wi-Fi could answer discovery with that id. Discovery only runs after the real hub has been
  unreachable for 3 minutes, but then:
  - a **collector** that switched to the fake hub would send it readings and its **write-only** token. That token
    can't read or delete your history, but it could be used to write junk readings.
  - a **display** that switched to it would show whatever the fake hub said, and the fake hub would get the display's
    **read-only** token, **which can read your whole reading history**.

  If you're worried, give the hub a DHCP reservation. If you ever see a "hub moved" message you didn't expect,
  replace both tokens: blank `NODE_WRITE_TOKEN` and `INFLUX_READ_TOKEN` in `hub/.env`, delete the old tokens in
  InfluxDB, run `./setup.sh`, and re-join your devices with the new codes. If you have the status sign, put the new
  read-only token (`INFLUX_READ_TOKEN`) in its `secrets.py` too, or it will quietly stop getting data. (On a trusted network this is no worse than the plain-HTTP
  limit above: a device that can impersonate the hub could already see the token in transit.) A future version will
  have the hub prove its identity with a key carried only in the join code, so an impostor can't.
- **The display web pages (ports 8090 and 8091) have no password.** They show readings and collector names to
  anyone on your network. Don't open them to the internet.
