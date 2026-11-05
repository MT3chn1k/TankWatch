#!/bin/sh
# First-time hub setup. Safe to run again: it only fills in what's missing, then prints the join codes.
#   ./setup.sh          set up (or check) the hub and print join codes
#   ./setup.sh codes    just print the join codes again
#   ./setup.sh widget   turn on the phone widget add-on (./setup.sh widget off turns it off again)
set -eu
cd "$(dirname "$0")"

rand() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
get() { sed -n "s/^$1=//p" .env; }
put() { # put KEY VALUE: set KEY in .env if it's empty (adding the line if it's missing)
  if ! grep -q "^$1=" .env; then echo "$1=" >> .env; fi
  if [ -z "$(get "$1")" ]; then sed -i "s|^$1=.*|$1=$2|" .env; fi
}
set_() { # set_ KEY VALUE: set KEY in .env, replacing what's there
  if ! grep -q "^$1=" .env; then echo "$1=" >> .env; fi
  sed -i "s|^$1=.*|$1=$2|" .env
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

port() { v=$(get "$1"); echo "${v:-$2}"; }   # port NAME DEFAULT: a port from .env, or its default
IPORT() { port INFLUX_PORT 8086; }; GPORT() { port GRAFANA_PORT 3000; }; APORT() { port ADMIN_PORT 8088; }
WPORT() { port WIDGET_PORT 8089; }
widget_on() { case ",$(get COMPOSE_PROFILES)," in *,widget,*) return 0 ;; *) return 1 ;; esac; }

tailscale_ip() { # the hub's Tailscale address, if Tailscale is installed and up (for the phone widget, away from home)
  command -v tailscale >/dev/null 2>&1 && tailscale ip -4 2>/dev/null | grep -Em1 '^100\.' || true
}

b64url() { base64 | tr -d '\n=' | tr '+/' '-_'; }

join_code() { # join_code ROLE TOKEN: everything a collector (or display) needs, in one line
  printf '{"v":1,"id":"%s","u":"http://%s:%s","o":"%s","b":"%s","r":"%s","t":"%s"}' \
    "$(get HUB_ID)" "$(lan_ip)" "$(IPORT)" "$(get INFLUX_ORG)" "$(get INFLUX_BUCKET)" "$1" "$2" | b64url | sed 's/^/tw1./'
}

print_codes() {
  ip=$(lan_ip)
  cat <<MSG

TankWatch hub "$(get HUB_NAME)" is running at $ip
  Dashboards: http://$ip:$(GPORT)   user $(get GRAFANA_ADMIN_USER), password $(get GRAFANA_ADMIN_PASSWORD)
  Admin page: http://$ip:$(APORT)   user admin, password $(get ADMIN_PASSWORD)
              (collector status, adding a sensor Pi, the status sign's config$(widget_on && echo ", pairing phones"))

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
if [ "${1:-}" = widget ] && [ "${2:-}" = off ]; then   # paired phones are kept, in case you turn it on again
  set_ COMPOSE_PROFILES "$(echo ",$(get COMPOSE_PROFILES)," | sed 's/,widget,/,/; s/^,*//; s/,*$//')"
  docker compose --profile widget stop widget >/dev/null 2>&1 || true
  docker compose --profile widget rm -f widget >/dev/null 2>&1 || true
  echo "Phone widget add-on turned off. Turn it on again with: ./setup.sh widget"
  exit 0
fi
if [ "${1:-}" = widget ]; then
  cur=$(get COMPOSE_PROFILES); widget_on || set_ COMPOSE_PROFILES "${cur:+$cur,}widget"
  echo "Phone widget add-on on: setting up the hub with it..."
fi

put INFLUX_ADMIN_PASSWORD "$(rand 24)"
put INFLUX_ADMIN_TOKEN "$(rand 48)"
put GRAFANA_ADMIN_PASSWORD "$(rand 16)"
put ADMIN_PASSWORD "$(rand 20)"
put HUB_ID "$(rand 12)"
put HUB_NAME "$(hostname 2>/dev/null || echo tankwatch-hub)"
put WIDGET_ADMIN_TOKEN "$(rand 40)"    # lets the admin page pair phones through the widget service (never leaves the hub)

# The beacon only says "a TankWatch hub lives here" and which hub it is. No tokens or passwords.
mkdir -p beacon
printf '{"tankwatch": "hub", "v": 1, "id": "%s", "name": "%s", "influx_port": %s, "grafana_port": %s}\n' \
  "$(get HUB_ID)" "$(get HUB_NAME)" "$(IPORT)" "$(GPORT)" > beacon/tankwatch.json

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

set_ HUB_DETECTED_ADDRESS "$(lan_ip)"
ts=$(tailscale_ip); set_ WIDGET_DETECTED_REMOTE_URL "${ts:+http://$ts:$(WPORT)}"
docker compose up -d --quiet-pull --build

# Check the hub answers on its network address, not just on this machine
ip=$(lan_ip)
for port in $(IPORT) 8087 $(GPORT) $(APORT) $(widget_on && WPORT); do                 # give each up to 30 s: Grafana takes a moment to start
  n=0; until curl -s -m 3 -o /dev/null "http://$ip:$port/" || [ $n -ge 10 ]; do n=$((n + 1)); sleep 3; done
  if [ $n -ge 10 ]; then
    echo "WARNING: nothing answered on $ip:$port. Other devices won't reach the hub until that works."
    echo "         Check this machine's firewall allows Docker on ports $(IPORT), 8087, $(GPORT) and $(APORT)."
  fi
done
print_codes
