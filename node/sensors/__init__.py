"""Sensor plug-ins. Each module defines `Sensor(options)` with a `read()` method that returns a list of
(measurement, tags, fields) tuples. To add a sensor, copy mock.py, rename it, and use its file name as
`type:` in config.yaml. See docs/adding-a-sensor.md."""


def c_to_f(c):
    return round(c * 9 / 5 + 32, 1)
