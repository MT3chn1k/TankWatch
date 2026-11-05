# TankWatch admin page

One page on the hub for looking after your collectors: `http://<hub>:8088`, user `admin`, password
`ADMIN_PASSWORD` from `hub/.env` (`hub/setup.sh` creates it and prints it with the join codes).

| Section | What it does |
|---|---|
| **Collectors** | Every sensor Pi heard from in the last 7 days: green (reporting), amber (undervolted, throttled or hot), red (silent for 90 seconds), with CPU temperature, memory, disk and which locations it reports. A Pi that joined in the last hour is marked **new**. |
| **Add a sensor Pi** | The steps for a new collector: wiring, Docker, the setup wizard, and the **collector join code** to paste into it. Then **Watch for a new collector** tells you when the new Pi first reports. |
| **Readings** | Every location, what kind of reading, which collector and sensor, the latest values and when they came in. |
| **Displays** | The read-only **display join code** for the Unicorn HAT Mini and the status sign. |
| **Status sign config** | Builds the sign's `config.json` from your actual collectors and locations: pick up to 4 collectors and their labels, which air and water readings to show, and the colour ranges. Download it and copy it to the sign. |
| **Hub** | Whether InfluxDB, Grafana and the discovery beacon are answering, and links to them. |

## It only reads

The page changes nothing on the hub. It queries InfluxDB with the **read-only** token. The collector's write-only
token is only there to build the collector join code. The sign config is built in your browser.

## Starting it

It's part of the hub: `hub/setup.sh` starts it with everything else. A hub set up before the admin page existed:

```sh
cd tankwatch && git pull
cd hub && ./setup.sh       # adds ADMIN_PASSWORD to .env and starts the admin page
```

## The address in the join codes

The codes point collectors at the address you used to open this page, so open it by the hub's network address
(for example `http://192.168.1.10:8088`), not `localhost`. If that's not the address collectors should use, set
`HUB_ADDRESS=` in `hub/.env` and run `./setup.sh` again. A collector that's pointed at the wrong address still
finds the hub by discovery, just more slowly.

## Security

- Password protected, because the join codes are secrets. After 10 wrong passwords from one address it stops
  answering that address for 10 minutes.
- Plain HTTP, like the rest of TankWatch: for a trusted home network only. Never forward port 8088 on your router.
  To look in from outside, use a VPN such as WireGuard or Tailscale.
- The container runs as an unprivileged user with no Linux capabilities, a read-only filesystem and no way to gain
  privileges. Its pages forbid inline scripts and being framed by other sites.

To change the password: edit `ADMIN_PASSWORD` in `hub/.env`, then `docker compose up -d admin` in `hub/`.
