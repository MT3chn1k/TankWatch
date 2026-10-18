# Installing a collector without Docker

On Raspberry Pi OS / Debian 12 or newer:

```sh
sudo apt install -y python3-venv libgpiod2 git curl
sudo git clone https://github.com/MT3chn1k/tankwatch.git /opt/tankwatch
sudo chown -R pi: /opt/tankwatch
python3 -m venv /opt/tankwatch/venv
/opt/tankwatch/venv/bin/pip install -r /opt/tankwatch/node/requirements.txt
cd /opt/tankwatch/node
./setup.sh --no-docker        # joins the hub, detects sensors, writes tankwatch.yaml; skips Docker
/opt/tankwatch/venv/bin/python tankwatch_node.py --test     # read every sensor once
sudo cp tankwatch-node.service /etc/systemd/system/
sudo systemctl enable --now tankwatch-node
journalctl -u tankwatch-node -f
```

If `setup.sh` offers to switch on 1-Wire for DS18B20 probes, accept, reboot, and run `./setup.sh --no-docker` again
to find the probes.
