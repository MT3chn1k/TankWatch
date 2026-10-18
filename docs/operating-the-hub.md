# Operating the hub

Day-to-day care of the hub: backups, restores, upgrades, security, and what to check when something's wrong.

## Backups

```sh
cd tankwatch/hub
./backup.sh
```

Each run writes `hub/backups/<date_time>/` with two things:

- `influxdb/`: every reading, plus buckets, users and tokens (InfluxDB's own `influx backup`)
- `grafana.db`: dashboards, Grafana users and any alert rules you've made

It keeps the newest 7 backups (`KEEP=30 ./backup.sh` keeps more). Run it nightly with cron (`crontab -e`):

```
30 3 * * * /home/pi/tankwatch/hub/backup.sh >> /home/pi/tankwatch/hub/backups/backup.log 2>&1
```

A backup on the hub's own disk won't survive that disk dying. Copy `hub/backups/` somewhere else too: a
USB stick, another computer, or a NAS. Also keep a copy of `hub/.env` somewhere private. Without it you
can't log in to a restored hub with your old passwords.

## Restoring

```sh
./restore.sh backups/2026-10-18_0330
```

This **replaces everything** in InfluxDB and Grafana with the backup's contents, so it asks you to type `yes`
first. Collectors keep their readings in memory while the hub is down and send them once it's back, so a short
restore loses nothing new.

Restoring onto a new machine: clone the repo, copy your old `hub/.env` and the backup folder into `hub/`,
run `./setup.sh` once to start the containers, then `./restore.sh`. If the new machine has a different IP
address, update `INFLUX_URL` in each collector's `.env` and `hub_url` in the sign's `config.json`.

> Restoring by hand? After `docker compose cp` puts `grafana.db` back, the file belongs to root and Grafana
> (user 472) can't write it. Grafana then restarts in a loop with "attempt to write a readonly database".
> `restore.sh` fixes the owner for you.

## Upgrading

The InfluxDB and Grafana versions are pinned in `hub/docker-compose.yml`, so nothing changes under you.
To upgrade, take a backup, edit the image tags, then:

```sh
./backup.sh
docker compose pull && docker compose up -d
```

Collectors: `git pull`, then `docker compose up -d --build` in `node/`.

## Security

- **Keep the hub on your home network.** Don't forward ports 3000 or 8086 on your router. To check your
  tanks from outside, use a VPN such as WireGuard or Tailscale.
- `hub/.env` holds every password and token. It's ignored by git; keep it that way, with `chmod 600`
  (setup.sh does this).
- Collectors have **write-only** tokens and Grafana a **read-only** one. If a collector is lost or stolen,
  make a new write token and delete the old one in InfluxDB (`http://<hub>:8086` → Load Data → API Tokens).

## Ports

| Port | Service | Who connects |
|---|---|---|
| 3000 | Grafana | You, in a browser |
| 8086 | InfluxDB | Collectors (write), the status sign (read), you (admin UI) |

## When something's wrong

| Symptom | Check |
|---|---|
| A collector's readings stopped | On that collector: `docker logs --tail 30 tankwatch-node`. "could not start" means a sensor isn't wired or the pin is wrong. The rest of that collector keeps running. "hub unreachable" means it can't reach the hub; it's buffering and will catch up. |
| "hub rejected ... HTTP 401" in a collector's log | Its `INFLUX_TOKEN` is wrong or was deleted. Copy `NODE_WRITE_TOKEN` from `hub/.env`. |
| DHT sensor: "could not start" | Is GPIO given to the container (`devices:` in `node/docker-compose.yml`)? Is the `pin:` right (`D17` = GPIO17 = physical pin 11)? |
| DS18B20: "no probe found" | Is `dtoverlay=w1-gpio` in `/boot/firmware/config.txt` (then reboot)? Is the 4.7 kΩ resistor between data and 3.3 V? Is `/sys/bus/w1` mounted in `node/docker-compose.yml`? |
| Grafana won't start after a restore | See the note under Restoring. |
| Dashboards are empty | Is the time range right (top right)? Are the Location / Node pickers on All? Are any collectors running? |
| The status sign shows a collector red | That collector hasn't reported for 90 seconds. Check its power, network and `docker logs`. |
