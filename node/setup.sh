#!/usr/bin/env bash
# TankWatch collector setup. Run on the Pi that has the sensors:  ./setup.sh
# Safe to run again (new probe, moved sensor): it keeps the hub settings and offers your previous answers.
#
# Options (all optional, for scripted installs):
#   --join CODE        collector join code from the hub (./setup.sh codes on the hub)
#   --name NAME        collector name (default: this Pi's host name)
#   --yes              accept defaults instead of asking (locations become "tank-1", "room", ...)
#   --no-docker        do everything except build and start the container (for running it as a systemd service)
#   --dry-run          only write tankwatch.yaml and the Docker settings: change nothing else on this machine
set -euo pipefail
cd "$(dirname "$0")"

JOIN="" NAME="" YES=0 DRY=0 NODOCKER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --join) JOIN=$2; shift 2 ;;
    --name) NAME=$2; shift 2 ;;
    --yes) YES=1; shift ;;
    --dry-run) DRY=1; NODOCKER=1; shift ;;
    --no-docker) NODOCKER=1; shift ;;
    -h|--help) sed -n '2,10p' "$(basename "$0")"; exit 0 ;;   # we're already in the script's folder
    *) echo "unknown option $1 (try --help)"; exit 1 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
ask() { # ask "Question" default -> answer (the default when --yes or just Enter)
  local a=""
  if [ "$YES" = 1 ]; then echo "$2"; return; fi
  read -r -p "$1 [$2]: " a || true
  echo "${a:-$2}"
}
yesno() { [ "$YES" = 1 ] && return 0; local a; read -r -p "$1 [Y/n]: " a || true; [[ ! "$a" =~ ^[Nn] ]]; }
helper() { python3 setup_helpers.py "$@"; }

# --- 1. Docker ---------------------------------------------------------------------------------------
if [ "$NODOCKER" = 0 ] && ! command -v docker >/dev/null; then
  say "Docker isn't installed"
  echo "This uses Docker's official install script (https://get.docker.com). To install by hand instead, follow"
  echo "https://docs.docker.com/engine/install/debian/ then run ./setup.sh again."
  yesno "Install it now (takes a few minutes)?" || { echo "Docker is needed. Stopping."; exit 1; }
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
DOCKER="docker"
if [ "$NODOCKER" = 0 ] && ! docker info >/dev/null 2>&1; then DOCKER="sudo docker"; fi

# --- 2. Hub -------------------------------------------------------------------------------------------
HUB_JSON=""
if [ -f tankwatch.yaml ] && [ -z "$JOIN" ]; then
  HUB_JSON=$(helper read-hub tankwatch.yaml)
  [ -n "$HUB_JSON" ] && say "Keeping the hub settings already in tankwatch.yaml"
fi
if [ -z "$HUB_JSON" ]; then
  say "Joining a hub"
  if [ -z "$JOIN" ]; then
    [ "$YES" = 1 ] && { echo "--yes needs --join CODE"; exit 1; }
    echo "On the hub, run ./setup.sh codes and copy the COLLECTOR join code (starts with tw1.)."
    read -r -p "Paste it here: " JOIN
  fi
  HUB_JSON=$(helper join "$JOIN") || exit 1
fi
HUB_ID=$(helper get "$HUB_JSON" id)
HUB_URL=$(helper get "$HUB_JSON" url)

if curl -s -m 3 -o /dev/null "$HUB_URL/health"; then
  echo "Hub answers at $HUB_URL"
else
  echo "The hub didn't answer at $HUB_URL. Looking for it on the network (up to a minute)..."
  FOUND=$(helper find "$HUB_ID" "$HUB_URL")
  if [ -n "$FOUND" ]; then
    echo "Found it at $FOUND"; HUB_URL=$FOUND
  else
    echo "Not found. Check the hub is on, and this Pi is on the same network as it."
    HUB_URL=$(ask "Hub address to use anyway (the hub prints it when you run ./setup.sh codes)" "$HUB_URL")
  fi
fi

# --- 3. Name ------------------------------------------------------------------------------------------
PREV_NAME=$(helper previous tankwatch.yaml node)
NAME=${NAME:-$(ask "Name for this collector (shows in dashboards and on the sign)" "${PREV_NAME:-$(hostname)}")}

# --- 4. Sensors ---------------------------------------------------------------------------------------
say "Looking for sensors"
SENSORS="  - type: node_health        # this Pi's own health: CPU temperature, undervoltage, memory, disk
    interval_s: 30
"
OVERRIDE_VOLUMES="" OVERRIDE_DEVICES=""

W1=${W1_DEVICES:-/sys/bus/w1/devices}          # override only for testing with fake probes
CONFIG_TXT=/boot/firmware/config.txt; [ -f $CONFIG_TXT ] || CONFIG_TXT=/boot/config.txt
if [ -d $W1 ]; then
  PROBES=$(ls $W1 2>/dev/null | grep '^28-' || true)
  if [ -n "$PROBES" ]; then
    echo "Found $(echo "$PROBES" | wc -l) DS18B20 temperature probe(s)."
    n=0
    for p in $PROBES; do
      n=$((n + 1))
      t=$(awk -F't=' '/t=/{printf "%.1f", $2 / 1000 * 9 / 5 + 32}' $W1/$p/w1_slave 2>/dev/null || echo "?")
      prev=$(helper previous tankwatch.yaml "probe:$p")
      loc=$(ask "  Probe $p reads ${t}F. Where is it (a tank, a reservoir...)" "${prev:-tank-$n}")
      SENSORS+="  - type: ds18b20            # probe $p
    location: $loc
    interval_s: 60
    options: {only: [$p]}
"
    done
    OVERRIDE_VOLUMES+="      - /sys/bus/w1:/sys/bus/w1:ro
"
  else
    echo "1-Wire is on, but no DS18B20 probe answers. (Check the probe's wiring and its 4.7k resistor.)"
  fi
elif [ -f "$CONFIG_TXT" ] && ! grep -q '^dtoverlay=w1-gpio' "$CONFIG_TXT"; then
  if yesno "1-Wire (for DS18B20 water probes) is off. Turn it on? It takes effect after a reboot"; then
    if [ "$DRY" = 1 ]; then echo "(dry run: would add dtoverlay=w1-gpio to $CONFIG_TXT)"
    else
      BACKUP="$CONFIG_TXT.bak-tankwatch-$(date +%Y%m%d-%H%M%S)"     # this file controls how the Pi boots: copy it first
      sudo cp -p "$CONFIG_TXT" "$BACKUP"
      echo "dtoverlay=w1-gpio" | sudo tee -a "$CONFIG_TXT" >/dev/null
      echo "Added dtoverlay=w1-gpio to $CONFIG_TXT. The original is saved as $BACKUP"
      NEED_REBOOT=1
    fi
  fi
fi

DHT=$(ask "Is a DHT air sensor wired? (11 = DHT11, 22 = DHT22, n = none)" "$(helper previous tankwatch.yaml dht || echo n)")
if [[ "$DHT" =~ ^(11|22)$ ]]; then
  prev=$(helper previous tankwatch.yaml dht-pin)
  PIN=$(ask "  Which GPIO is its data wire on? (GPIO17 = physical pin 11)" "${prev:-17}")
  prev=$(helper previous tankwatch.yaml dht-location)
  loc=$(ask "  Where is it" "${prev:-room}")
  SENSORS+="  - type: dht                # DHT$DHT air temperature and humidity on GPIO$PIN
    location: $loc
    interval_s: 60
    options: {model: dht$DHT, pin: D$PIN}
"
  if [ -e /dev/gpiomem ]; then OVERRIDE_DEVICES+="      - /dev/gpiomem
"; fi                                                                       # Pi 3 / Pi 4
  for c in /dev/gpiochip0 /dev/gpiochip4; do [ -e $c ] && OVERRIDE_DEVICES+="      - $c
"; done                                                                    # Pi 5
fi

# --- 5. Write the config ------------------------------------------------------------------------------
say "Writing tankwatch.yaml"
umask 077
helper config "$HUB_JSON" "$HUB_URL" "$NAME" > tankwatch.yaml
printf 'sensors:\n%s' "$SENSORS" >> tankwatch.yaml
chmod 600 tankwatch.yaml

# The collector runs as whoever ran setup.sh (it owns tankwatch.yaml, which only its owner can read), and joins the
# gpio group only if a DHT sensor needs the GPIO pins
GPIO_GID=""
[ -n "$OVERRIDE_DEVICES" ] && GPIO_GID=$(getent group gpio 2>/dev/null | cut -d: -f3 || true)
{
  echo "# This Pi's settings for the collector container, written by setup.sh."
  echo "services:"
  echo "  node:"
  echo "    user: \"$(id -u):$(id -g)\""
  [ -n "$GPIO_GID" ] && printf '    group_add: ["%s"]\n' "$GPIO_GID"
  [ -n "$OVERRIDE_VOLUMES" ] && printf '    volumes:\n%s' "$OVERRIDE_VOLUMES"
  [ -n "$OVERRIDE_DEVICES" ] && printf '    devices:\n%s' "$OVERRIDE_DEVICES"
} > docker-compose.override.yml
echo "Sensors:"; grep -E '^  - type:' tankwatch.yaml | sed 's/^  - type: /  /'

if [ "${NEED_REBOOT:-0}" = 1 ]; then
  say "Reboot needed"
  echo "1-Wire turns on after a reboot. Run: sudo reboot   then run ./setup.sh again to find your probes."
  exit 0
fi
if [ "$DRY" = 1 ]; then say "Dry run: nothing built or started"; exit 0; fi
if [ "$NODOCKER" = 1 ]; then say "Config written. Start the collector with: sudo systemctl restart tankwatch-node"; exit 0; fi

# --- 6. Test, then start ------------------------------------------------------------------------------
say "Building the collector (the first build takes a few minutes on a Pi)"
$DOCKER compose build --quiet
say "Testing each sensor once"
if ! $DOCKER compose run --rm --no-deps node python tankwatch_node.py --test; then
  echo
  echo "Some sensors failed. The collector will still start, keep the working ones running, and retry the"
  echo "others every 5 minutes. Fix the wiring, or re-run ./setup.sh to change the sensor list."
fi
say "Starting the collector"
$DOCKER compose up -d
sleep 8
$DOCKER compose logs --tail 15 node
HUB_HOST=$(helper host "$HUB_URL")
cat <<MSG

Done. "$NAME" is sending readings to the hub. See them at http://$HUB_HOST:3000
Watch this collector:  $DOCKER logs -f tankwatch-node
MSG
