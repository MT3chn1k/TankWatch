#!/bin/sh
# First-time hub setup. Safe to run again: it only fills in what's missing.
set -eu
cd "$(dirname "$0")"

rand() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
get() { sed -n "s/^$1=//p" .env; }
put() { # put KEY VALUE: set KEY in .env if it's empty
  if [ -z "$(get "$1")" ]; then sed -i "s|^$1=.*|$1=$2|" .env; fi
}

[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "created .env"; }
put INFLUX_ADMIN_PASSWORD "$(rand 24)"
put INFLUX_ADMIN_TOKEN "$(rand 48)"
put GRAFANA_ADMIN_PASSWORD "$(rand 16)"

docker compose up -d --quiet-pull influxdb
printf "waiting for InfluxDB"
until [ "$(docker inspect -f '{{.State.Health.Status}}' tankwatch-influxdb)" = healthy ]; do printf .; sleep 3; done
echo

ORG=$(get INFLUX_ORG); BUCKET=$(get INFLUX_BUCKET)
influx() { docker compose exec -T influxdb influx "$@" --token "$(get INFLUX_ADMIN_TOKEN)"; }
BUCKET_ID=$(influx bucket list --org "$ORG" --name "$BUCKET" --hide-headers | awk '{print $1}')

token_for() { # token_for DESCRIPTION FLAG: create a token scoped to the sensors bucket
  influx auth create --org "$ORG" --description "$1" "$2" "$BUCKET_ID" --json | sed -n 's/.*"token": "\([^"]*\)".*/\1/p'
}
[ -n "$(get INFLUX_READ_TOKEN)" ] || put INFLUX_READ_TOKEN "$(token_for tankwatch-grafana-read --read-bucket)"
[ -n "$(get NODE_WRITE_TOKEN)" ] || put NODE_WRITE_TOKEN "$(token_for tankwatch-node-write --write-bucket)"

docker compose up -d --quiet-pull
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<MSG

TankWatch hub is running.
  Grafana:  http://${IP:-this-host}:3000   user $(get GRAFANA_ADMIN_USER), password $(get GRAFANA_ADMIN_PASSWORD)
  InfluxDB: http://${IP:-this-host}:8086

Put these lines in each sensor node's node/.env:
  INFLUX_URL=http://${IP:-this-host}:8086
  INFLUX_ORG=$ORG
  INFLUX_BUCKET=$BUCKET
  INFLUX_TOKEN=$(get NODE_WRITE_TOKEN)

All passwords and tokens are in hub/.env. Keep that file private.
MSG
