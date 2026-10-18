#!/bin/sh
# Stop the TankWatch lab. --wipe also deletes the lab hub's data, so the next start is a fresh install.
set -eu
cd "$(dirname "$0")"
docker compose down 2>/dev/null || true
if [ -d run/hub ]; then
  if [ "${1:-}" = --wipe ]; then
    (cd run/hub && COMPOSE_PROJECT_NAME=tw-lab-hub docker compose down -v)
    rm -f run/hub/.env run/hub-setup.log .env
    echo "lab stopped and wiped"
  else
    (cd run/hub && COMPOSE_PROJECT_NAME=tw-lab-hub docker compose down)
    echo "lab stopped (data kept; ./stop.sh --wipe to delete it)"
  fi
fi
