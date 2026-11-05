#!/bin/sh
# Start the TankWatch virtual test lab on this computer (needs Docker).
# Sets up a lab hub with the real hub/setup.sh, then starts four collectors and two displays that join it with
# the join codes it prints. Safe to run again. Stop with ./stop.sh
set -eu
cd "$(dirname "$0")"
# python3 or python, whichever really runs (Windows has a "python3" that only opens the Microsoft Store)
PY=""; for p in python3 python; do if "$p" -c "import sys" >/dev/null 2>&1; then PY=$p; break; fi; done
[ -n "$PY" ] || { echo "Python 3 is needed to start the lab"; exit 1; }

mkdir -p run/hub
cp -r ../hub/. run/hub/                        # a private copy, so the lab never touches your real hub's .env
mkdir -p run/admin && cp -r ../admin/. run/admin/   # the hub builds its admin page from ../admin
mkdir -p run/widget && cp -r ../widget/. run/widget/  # and the optional phone widget service from ../widget
if [ ! -f run/hub/.env ]; then
  cp run/hub/.env.example run/hub/.env
  sed -i 's/^HUB_NAME=.*/HUB_NAME=tw-lab-hub/' run/hub/.env
fi
echo "Setting up the lab hub..."
# "widget": the lab hub runs the optional phone widget add-on too, turned on the way a user would
(cd run/hub && COMPOSE_PROJECT_NAME=tw-lab-hub ./setup.sh widget) > run/hub-setup.log 2>&1 || { cat run/hub-setup.log; exit 1; }
grep -E "WARNING|running at" run/hub-setup.log || true

COLLECTOR_CODE=$(grep -E '^  tw1\.' run/hub-setup.log | sed -n 1p | tr -d ' \r')
DISPLAY_CODE=$(grep -E '^  tw1\.' run/hub-setup.log | sed -n 2p | tr -d ' \r')
# The same collector code, but pointing at an address where no hub is: kitchen-pi must find the hub itself
STALE_COLLECTOR_CODE=$("$PY" - "$COLLECTOR_CODE" <<'PYEOF'
import base64, json, sys
raw = sys.argv[1][4:]; d = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
d["u"] = "http://10.254.254.254:8086"
print("tw1." + base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("="))
PYEOF
)
umask 077
printf 'COLLECTOR_CODE=%s\nDISPLAY_CODE=%s\nSTALE_COLLECTOR_CODE=%s\n' "$COLLECTOR_CODE" "$DISPLAY_CODE" "$STALE_COLLECTOR_CODE" > .env

# Pair one "lab phone" the first time; its token is kept in run/ (private) so check.py can use it on every run
if [ ! -s run/widget-token ]; then
  LINK=$(cd run/hub && COMPOSE_PROJECT_NAME=tw-lab-hub docker compose exec -T widget python widget.py pair "lab phone" \
         | grep '^tankwatch://' | tr -d '\r' || true)
  if [ -n "$LINK" ]; then
    (umask 077; printf '%s\n' "$LINK" | sed 's/.*[?&]t=\([^&]*\).*/\1/' > run/widget-token)
  else
    echo "WARNING: couldn't pair the lab phone with the widget service (check.py will say so)"
  fi
fi

echo "Starting collectors and displays..."
docker compose up -d --build --quiet-pull 2>&1 | grep -vE "^ *(Container|Network|Image|#)" || true
cat <<MSG

TankWatch lab is running:
  Dashboards         http://localhost:3000   (login in lab/run/hub/.env: GRAFANA_ADMIN_USER / _PASSWORD)
  Unicorn HAT Mini   http://localhost:8090   (virtual display Pi)
  Status sign        http://localhost:8091   (virtual Galactic Unicorn, running the real sign code)
  Phone widget data  http://localhost:8089/v1/summary   (needs the lab phone's token: lab/run/widget-token)
Check it:  python lab/check.py      Stop it:  lab/stop.sh
MSG
