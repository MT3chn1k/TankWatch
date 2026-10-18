#!/bin/sh
# Back up the hub: all InfluxDB data and settings (influx backup) plus Grafana's database (dashboards,
# users, alert rules). Writes hub/backups/<date_time>/ and keeps the newest KEEP backups (default 7).
#   ./backup.sh            run a backup
#   KEEP=30 ./backup.sh    keep more
# Run it nightly from cron:  30 3 * * * /path/to/tankwatch/hub/backup.sh >> /path/to/tankwatch/hub/backups/backup.log 2>&1
# Restore steps are in docs/operating-the-hub.md.
set -eu
cd "$(dirname "$0")"
KEEP=${KEEP:-7}
token=$(sed -n 's/^INFLUX_ADMIN_TOKEN=//p' .env)
[ -n "$token" ] || { echo "no INFLUX_ADMIN_TOKEN in hub/.env; run ./setup.sh first" >&2; exit 1; }

quiet() { # quiet "what this step does" command...: run silently; on failure say which step and show its output
  step=$1; shift
  out=$("$@" 2>&1) || { echo "backup FAILED: $step" >&2; echo "$out" >&2; exit 1; }
}

stamp=$(date +%Y-%m-%d_%H%M)
dest=backups/$stamp
mkdir -p "$dest"

quiet "InfluxDB backup" docker compose exec -T influxdb sh -c "rm -rf /tmp/tw-backup && influx backup /tmp/tw-backup -t '$token'"
quiet "copying the InfluxDB backup out" docker compose cp influxdb:/tmp/tw-backup "$dest/influxdb"
quiet "cleaning up" docker compose exec -T influxdb rm -rf /tmp/tw-backup
# Grafana keeps everything in one SQLite file; copying it while running is safe for a home-sized install.
quiet "copying grafana.db" docker compose cp grafana:/var/lib/grafana/grafana.db "$dest/grafana.db"

echo "$stamp influxdb=$(du -sh "$dest/influxdb" | cut -f1) grafana.db=$(du -sh "$dest/grafana.db" | cut -f1) -> $dest"

# Keep the newest $KEEP backups
ls -1d backups/20*/ 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do rm -rf "$old"; echo "removed $old"; done
