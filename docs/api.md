# API reference

## MP4

```python
from rpi360 import Player

with Player.mp4("capture.r360.mp4") as player:
    frame = player.next(timeout=None)
    if frame is not None:
        perspective = frame.image
        equi_1 = frame.output("equi_1")
        equi_2 = frame.output("equi_2")
        panorama = frame.output("equi_blended")
```

MP4 players additionally support `seek()`, `seek_by()`, `step()`, `restart()`,
`speed`, `duration`, `timeline`, and PTS-aware pacing.

## Live

```python
from rpi360 import Player

with Player.live("calibration-result.json") as player:
    while True:
        frame = player.next(timeout=0.03)
        if frame is not None:
            publish(frame.image)
```

Live pause keeps camera capture active and resumes at the latest pair. Timeline
operations raise `UnsupportedOperationError`.

## Views

```python
player.configure("perspective", size=(1280, 720), fov=100)
player.set_orientation(yaw=45, pitch=-10, roll=0)
player.rotate(yaw=3)
player.reset_view()
```

`set_orientation()` is absolute and is the correct choice for deterministic
animation. `rotate()` applies a local incremental rotation for interactive
controls.

## Recording

```python
with Player.live("calibration-result.json") as player:
    recording = player.start_recording("capture.r360.mp4")
    # Preview or publish frames independently here.
    output = recording.stop()
```

`RecordingHandle.stop()` is idempotent. Finalization muxes track IDs 1/2,
embeds both metadata tags, verifies them, and atomically publishes the output.
