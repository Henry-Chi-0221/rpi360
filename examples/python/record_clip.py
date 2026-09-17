"""Record ten seconds through the device API; run after opening the SSH tunnel."""

import os
from getpass import getpass
from time import sleep

from rpi360.client import DeviceClient


def main():
    camera = DeviceClient(
        os.environ.get("RPI360_URL", "http://127.0.0.1:8765"),
        token=os.environ.get("RPI360_TOKEN"),
    )
    if not camera.token:
        camera.pair(getpass("Pairing code from the Pi: "))
    camera.start_capture()
    camera.wait_for_sync(timeout=15)
    camera.start_recording()
    try:
        sleep(10)
    finally:
        recording = camera.stop_recording()
    print(recording["id"], recording["state"])


if __name__ == "__main__":
    main()
