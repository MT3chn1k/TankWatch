#!/bin/sh
# First-time hub setup. Safe to run again: it only fills in what's missing, then prints the join codes.
#   ./setup.sh          set up (or check) the hub and print join codes
#   ./setup.sh codes    just print the join codes again
set -eu
cd "$(dirname "$0")"

rand() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
get() { sed -n "s/^$1=//p" .env; }
put() { # put KEY VALUE: set KEY in .env if it's empty (adding the line if it's missing)
  if ! grep -q "^$1=" .env; then echo "$1=" >> .env; fi
  if [ -z "$(get "$1")" ]; then sed -i "s|^$1=.*|$1=$2|" .env; fi
}

lan_ip() { # this machine's address on the home network
  is_ip() { echo "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; }
  ip=$(get HUB_ADDRESS)                                       # set by hand in .env to override
  is_ip "$ip" || ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')
  case "$(uname -s)" in
    Darwin) is_ip "$ip" || ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true) ;;
    MINGW*|MSYS*|CYGWIN*) is_ip "$ip" || ip=$(powershell.exe -NoProfile -Command "(Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | Select-Object -First 1).IPv4Address.IPAddress" 2>/dev/null | tr -d '\r' || true) ;;
  esac
  is_ip "$ip" || ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  is_ip "$ip" && echo "$ip" || echo "this-host"
}

b64url() { base64 | tr -d '\n=' | tr '+/' '-_'; }

join_code() { # join_code ROLE TOKEN: everything a collector (or display) needs, in one line
  printf '{"v":1,"id":"%s","u":"http://%s:8086","o":"%s","b":"%s","r":"%s","t":"%s"}' \
    "$(get HUB_ID)" "$(lan_ip)" "$(get INFLUX_ORG)" "$(get INFLUX_BUCKET)" "$1" "$2" | b64url | sed 's/^/tw1./'
}

print_codes() {
  ip=$(lan_ip)
  cat <<MSG

TankWatch hub "$(get HUB_NAME)" is running at $ip
  Dashboards: http://$ip:3000   user $(get GRAFANA_ADMIN_USER), password $(get GRAFANA_ADMIN_PASSWORD)

Join code for collectors (sensor Pis). Paste it when node/setup.sh asks:

  $(join_code collector "$(get NODE_WRITE_TOKEN)")

Join code for displays (the status sign, HAT Mini displays). Read-only:

  $(join_code display "$(get INFLUX_READ_TOKEN)")

Each code contains a password-like token. Share it only with your own devices.
Print them again any time with: ./setup.sh codes
MSG
}

[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "created .env"; }
if [ "${1:-}" = codes ]; then print_codes; exit 0; fi

put INFLUX_ADMIN_PASSWORD "$(rand 24)"
put INFLUX_ADMIN_TOKEN "$(rand 48)"
put GRAFANA_ADMIN_PASSWORD "$(rand 16)"
put HUB_ID "$(rand 12)"
put HUB_NAME "$(hostname 2>/dev/null || echo tankwatch-hub)"

# The beacon only says "a TankWatch hub lives here" and which hub it is. No tokens or passwords.
mkdir -p beacon
printf '{"tankwatch": "hub", "v": 1, "id": "%s", "name": "%s", "influx_port": 8086, "grafana_port": 3000}\n' \
  "$(get HUB_ID)" "$(get HUB_NAME)" > beacon/tankwatch.json

docker compose up -d --quiet-pull influxdb
printf "waiting for InfluxDB"
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q influxdb)")" = healthy ]; do printf .; sleep 3; done
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

# Check the hub answers on its network address, not just on this machine
ip=$(lan_ip)
for port in 8086 8087 3000; do                 # give each up to 30 s: Grafana takes a moment to start
  n=0; until curl -s -m 3 -o /dev/null "http://$ip:$port/" || [ $n -ge 10 ]; do n=$((n + 1)); sleep 3; done
  if [ $n -ge 10 ]; then
    echo "WARNING: nothing answered on $ip:$port. Other devices won't reach the hub until that works."
    echo "         Check this machine's firewall allows Docker on ports 8086, 8087 and 3000."
  fi
done
print_codes
