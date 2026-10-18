# Installing a sensor node without Docker

On Raspberry Pi OS / Debian 12 or newer:

```sh
sudo apt install -y python3-venv libgpiod2 git
sudo git clone https://github.com/MT3chn1k/tankwatch.git /opt/tankwatch
sudo chown -R pi: /opt/tankwatch
python3 -m venv /opt/tankwatch/venv
/opt/tankwatch/venv/bin/pip install -r /opt/tankwatch/node/requirements.txt
cd /opt/tankwatch/node
cp .env.example .env && chmod 600 .env && nano .env
cp config.example.yaml config.yaml && nano config.yaml
sudo cp tankwatch-node.service /etc/systemd/system/
sudo systemctl enable --now tankwatch-node
journalctl -u tankwatch-node -f
```

For DS18B20 probes, add `dtoverlay=w1-gpio` to `/boot/firmware/config.txt` and reboot.
