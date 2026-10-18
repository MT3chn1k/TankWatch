# TankWatch displays

A display shows, at a glance, whether every collector is alive and what the latest readings are. It reads from the
hub with the **display join code**, which is read-only.

| Display | Hardware | How |
|---|---|---|
| **Unicorn HAT Mini** | Pimoroni Unicorn HAT Mini (17x7 LEDs) on any Raspberry Pi | `display/display.py` (this folder) |
| **Status sign** | Pimoroni Galactic Unicorn (53x11 LEDs, its own Pico 2 W, no Pi needed) | [sign/README.md](../sign/README.md) |
| Virtual versions of both | none: a web page | for the [test lab](../docs/test-lab.md), or any screen |

## What the Unicorn HAT Mini shows

- **The two right-hand columns** are one status light per collector, top to bottom in name order (up to 7):
  green = reporting, amber = reporting but undervolted, throttled or hot, red = silent for 90 seconds,
  grey = unknown (the hub itself isn't answering).
- **The rest is a scrolling ticker** of the latest readings: water and air temperature, humidity, and percentages
  like soil moisture and feeder level. It's led by a red `<NAME> DOWN` for any silent collector. Readings older
  than 15 minutes scroll in grey.

A collector shows up once it has reported at least once. One that was never set up can't be shown, since the hub
has never heard of it.

## Setting up a Unicorn HAT Mini on a Pi

Fit the HAT **directly on the Pi's 40-pin header**. Ribbon cables and adapters can swap pins and leave it dark.
Then:

```sh
sudo raspi-config nonint do_spi 0          # switch SPI on (the HAT uses it)
git clone https://github.com/MT3chn1k/tankwatch.git
cd tankwatch/display
echo "TANKWATCH_JOIN=<the display join code>" > .env && chmod 600 .env
docker compose up -d --build
```

Brightness: add `BRIGHTNESS=0.3` to `.env` (the default 0.15 is plenty indoors; 1.0 is dazzling).

## A virtual panel on any computer

```sh
cd tankwatch
docker build -f display/Dockerfile -t tankwatch-display .
docker run -d -p 8090:8090 -e TANKWATCH_JOIN=<display join code> -e PANEL=web tankwatch-display
```

Then open http://localhost:8090.
