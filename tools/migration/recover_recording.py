import argparse
import json

from rpi360_camera.recovery import recover

p = argparse.ArgumentParser(
    description="Recover fragments into a new directory; retain all source bytes"
)
p.add_argument("source")
p.add_argument("destination")
a = p.parse_args()
print(json.dumps(recover(a.source, a.destination), indent=2))
