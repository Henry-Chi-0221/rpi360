import argparse
import json
from pathlib import Path

from rpi360.core import convert_calibration

p = argparse.ArgumentParser(
    description="Compose legacy mount rotation into an explicit v2 calibration"
)
p.add_argument("source", type=Path)
p.add_argument("destination", type=Path)
a = p.parse_args()
value = convert_calibration(json.loads(a.source.read_text()))
with a.destination.open("x") as output:
    json.dump(value, output, indent=2)
    output.write("\n")
