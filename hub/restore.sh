#!/bin/sh
# Restore the hub from a backup made by backup.sh. This REPLACES everything currently in InfluxDB
# (readings, buckets, tokens) and Grafana (dashboards, users) with the backup's contents.
#   ./restore.sh backups/2026-10-18_0330          asks before overwriting
#   ./restore.sh backups/2026-10-18_0330 --yes    no question (for scripts)
set -eu
cd "$(dirname "$0")"
src=${1:-}
src=${src%/}
[ -d "$src/influxdb" ] && [ -f "$src/grafana.db" ] || {
  echo "usage: ./restore.sh backups/<date_time> [--yes]" >&2
  echo "available backups:" >&2; ls -1d backups/20*/ 2>/dev/null | sed 's|/$||' >&2
  exit 1
}
if [ "${2:-}" != "--yes" ]; then
  printf "Replace ALL current hub data and dashboards with %s? Type yes: " "$src"
  read -r answer
  [ "$answer" = yes ] || { echo "cancelled"; exit 1; }
fi
token=$(sed -n 's/^INFLUX_ADMIN_TOKEN=//p' .env)

quiet() { # quiet "what this step does" command...: run silently; on failure say which step and show its output
  step=$1; shift
  out=$("$@" 2>&1) || { echo "restore FAILED: $step" >&2; echo "$out" >&2; exit 1; }
}

echo "restoring InfluxDB from $src ..."
quiet "starting InfluxDB" docker compose up -d influxdb
quiet "preparing" docker compose exec -T influxdb rm -rf /tmp/tw-restore
quiet "copying the backup in" docker compose cp "$src/influxdb" influxdb:/tmp/tw-restore
quiet "InfluxDB restore" docker compose exec -T influxdb influx restore /tmp/tw-restore --full -t "$token"
quiet "cleaning up" docker compose exec -T influxdb rm -rf /tmp/tw-restore

echo "restoring Grafana ..."
quiet "stopping Grafana" docker compose stop grafana
quiet "copying grafana.db in" docker compose cp "$src/grafana.db" grafana:/var/lib/grafana/grafana.db
# docker cp leaves the file owned by root; Grafana runs as user 472 and can't start with a read-only database
quiet "fixing grafana.db ownership" docker compose run --rm --no-deps --user root --entrypoint chown grafana 472:0 /var/lib/grafana/grafana.db
quiet "starting Grafana" docker compose up -d grafana
echo "restored from $src. If the backup came from a different hub, copy that hub's .env here too:"
echo "the restored tokens and passwords are the backup's, not the ones in this .env."
