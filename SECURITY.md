# Security

## What TankWatch assumes

TankWatch is built for a **trusted home network**: your own Wi-Fi or wired network, used by people and devices
you trust.

- **Traffic is plain HTTP, not encrypted.** Readings, collector names and tokens travel across your network
  unencrypted, so any device on the same network can see them.
- **Don't run it on shared, guest, public or office Wi-Fi.** On a network you don't control, anyone else on it
  could read your tokens and readings.
- **Don't open the hub to the internet.** No port forwarding for 3000, 8086, 8087, 8090 or 8091. To check your
  tanks from away, use a VPN such as WireGuard or Tailscale.

Within that model, TankWatch limits the damage of a lost device or a leaked code:

- Collectors hold a **write-only** token and displays a **read-only** one. Neither can delete history or change
  the hub. The admin token never leaves the hub's `hub/.env`.
- Collector and display containers run with **no Linux capabilities**, a **read-only filesystem** and **no way to
  gain privileges**, and the collector runs as an ordinary user. See
  [docs/setup-and-discovery.md](docs/setup-and-discovery.md#what-the-containers-can-and-cant-do).
- Secrets live in files only their owner can read (`hub/.env`, `node/tankwatch.yaml`), which git ignores.

The known limits, including how a device on your network could impersonate the hub, are listed in
[docs/setup-and-discovery.md](docs/setup-and-discovery.md#known-limits).

## Reporting a problem

If you find a security problem, please **don't open a public issue**. Report it privately through GitHub:
the repository's **Security** tab, then **Report a vulnerability**. Include what you found, how to reproduce it,
and what it could let someone do. You'll get a reply as soon as possible.

Only the latest version on the `main` branch gets security fixes.
