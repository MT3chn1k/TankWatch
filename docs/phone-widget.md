# Phone widget (optional add-on)

A home-screen widget for Android that shows every location's latest water and air readings, colored by your
healthy ranges, and an overall status: all OK, a warning (a stale reading, an undervolted collector) or a
problem (a collector gone silent, water too hot or cold).

The add-on has two halves:

| Half | What it is | Status |
|---|---|---|
| **Widget service** on the hub | A small read-only summary for paired phones, on port 8089, and pairing on the admin page | Ready (this page) |
| **TankWatch app** for Android | The widget itself, paired by scanning a QR code | Coming next |

The widget service is **off unless you turn it on**. A hub without it runs exactly as before, with no extra port open.

## Turn it on

On the hub, in the `hub` folder:

```sh
./setup.sh widget
```

That adds `widget` to `COMPOSE_PROFILES` in `hub/.env` (so it stays on when you re-run setup or upgrade), then
builds and starts the `widget` service. It reads InfluxDB with the same **read-only** token as Grafana, so it
can't change or delete anything. If the hub has Tailscale, setup also finds the hub's Tailscale address for
phones to use away from home (see below).

To turn it off again: `./setup.sh widget off`. Paired phones are kept, in case you turn it on again.

## Pair a phone

On the admin page (`http://<hub>:8088`), go to **Phone widget**, type a name for the phone and press
**Pair a phone**. A QR code appears: scan it with the phone's camera, with the TankWatch app installed. Each phone
gets its own token, so you can revoke one (a lost phone) without touching the others; the list below the button
shows every paired phone and when it last checked in, with a **Revoke** button.

**The QR code holds the phone's token.** It's shown once and hides itself after 5 minutes. Don't screenshot it or
send it anywhere but that phone. The hub keeps only a hash of each token, so a lost code can't be shown again:
revoke the phone and pair it again.

Open the admin page by the hub's network address (not `localhost`), so the code points phones at the hub.

The same from the hub's command line, if you prefer:

```sh
docker compose exec widget python widget.py pair "Sam's phone"   # prints the pairing link
docker compose exec widget python widget.py list                  # paired phones and when each was last seen
docker compose exec widget python widget.py revoke 3f9a1c2e       # that phone's widget stops working at once
```

### How pairing is kept safe

- The pairing link's token is all a phone needs, and the hub stores only its hash.
- The admin page asks the widget service to pair or revoke over a **management port (8099) that isn't published**:
  only the admin page reaches it, inside the hub's Docker network, with a secret of its own (`WIDGET_ADMIN_TOKEN`,
  created by `setup.sh`). Port 8089, the one phones use, can't pair anything.
- Pairing and revoking on the admin page need its password, and are refused if another website tries to make your
  browser do them.

## What the widget shows, and the rules it uses

The service applies the same rules as the status sign and the displays, so they always agree:

| Shown as | When |
|---|---|
| Collector **down** (red) | No report for 90 seconds |
| Collector **warning** (amber) | Undervoltage, CPU throttling, or the CPU over 77 °C |
| Water **cold** / **hot** (blue / orange, a problem) | Outside `WATER_RANGE_F` |
| Air **cold** / **hot** (blue / orange, shown only) | Outside `AIR_RANGE_F` |
| Reading **stale** (grey, a warning) | Older than 15 minutes |

Set the healthy ranges in `hub/.env`, in °F, then run `./setup.sh` again:

```sh
WATER_RANGE_F=74,82
AIR_RANGE_F=68,80
```

For now one range covers every location. Per-location ranges, set on the admin page and shared with the status
sign, are planned.

If you want to see the data yourself (for example to build something else on it):

```sh
curl -H "Authorization: Bearer <the phone's token>" http://<hub>:8089/v1/summary
```

## Seeing your tanks from away from home

At home, the phone reaches the hub on your network. From anywhere else it needs a way in. In order of preference:

1. **Tailscale (recommended).** Install [Tailscale](https://tailscale.com) on the hub and on your phone, and
   keep it on. Nothing is opened to the internet. Run `./setup.sh` on the hub again: it finds the hub's Tailscale
   address, and the admin page shows it under **Phone widget**. Then pair the phone (again), so its QR code
   includes that address. The app tries your home address first, then the Tailscale one.

   Any other VPN you already run, such as WireGuard, works too: set the hub's address on it by hand in
   `hub/.env`, then pair again:

   ```sh
   WIDGET_REMOTE_URL=http://10.8.0.1:8089
   ```

2. **Tailscale Funnel for the widget only (optional).** If you want the widget to work without Tailscale on the
   phone, Funnel can publish **just this port** to the internet, with HTTPS:

   ```sh
   sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8089
   ```

   This is safe enough for this one service because it only reads a summary, answers only paired phones (every
   other request gets "not found"), and stops answering an address after 20 wrong tokens in 10 minutes. It
   has no join codes and can't write. Then set `WIDGET_REMOTE_URL=https://<hub>.<tailnet>.ts.net:8443` and
   pair again. Use port 8443 or 10000, **not 443**: Funnel on 443 takes over that port on the hub's Tailscale
   address. Funnel has to be allowed for the hub in your tailnet's access controls (Tailscale prints a link when
   it isn't).

3. **Your own HTTPS reverse proxy** (Caddy, nginx) on a domain you own, passing on only `/v1/` to port 8089. The
   same reasoning applies: only the widget service, always HTTPS.

**Never** forward ports on your router to the hub, and never publish the hub's other ports (InfluxDB, Grafana,
the admin page) by any of these routes. See [SECURITY.md](../SECURITY.md).

## Settings

All in `hub/.env` (the defaults work for most homes):

| Setting | Default | What it does |
|---|---|---|
| `WIDGET_PORT` | `8089` | The port the widget service listens on |
| `WIDGET_REMOTE_URL` | empty | The address to use from away from home; added to new pairing links. Empty: the hub's Tailscale address, if setup found one |
| `WATER_RANGE_F` | `74,82` | Healthy water range, °F |
| `AIR_RANGE_F` | `68,80` | Healthy air range, °F |

The pairing link's home address is the hub's address from `HUB_ADDRESS`, or the one `setup.sh` detected.
