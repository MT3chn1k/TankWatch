# Adding a sensor type

A sensor is one Python file in `node/sensors/`. The file name is the `type:` you use in `config.yaml`.

```python
# node/sensors/soil.py
from . import c_to_f


class Sensor:
    def __init__(self, options):
        # options = the `options:` block from config.yaml for this sensor
        self.channel = int(options.get("channel", 0))

    def read(self):
        # Return a list of (measurement, tags, fields).
        #   measurement: what kind of thing this is: "soil", "water", "air", "level" ...
        #   tags: extra labels to filter by (the agent adds node and location for you)
        #   fields: the numbers
        moisture = read_the_adc(self.channel)          # your hardware code here
        return [("soil", {"sensor": "capacitive-v1.2"}, {"moisture_pct": moisture})]
```

Rules that keep the dashboards working:

- **Temperatures:** send both `temp_c` and `temp_f` (use `c_to_f`). The dashboards' units switch picks one.
- **Raise an exception when a read fails.** The agent logs it and tries again next interval. Don't send a
  made-up or default value.
- **Filter impossible values** (see `ds18b20.py`, which drops the probe's 85 °C power-on reading).
- **Keep a field's type the same forever.** InfluxDB rejects a field that changes from number to text.
- Add any new Python packages to `node/requirements.txt`.

Then add it to `config.yaml`:

```yaml
  - type: soil
    location: fiddle-leaf-fig
    interval_s: 300
    options: {channel: 0}
```
