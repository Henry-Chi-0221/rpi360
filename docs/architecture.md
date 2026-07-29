# Architecture

```text
checkerboard -> K/D for camera 0 and camera 1
                         |
recorded calibration pair -> SIFT + spherical RANSAC + SVD -> rig rotation
                         |
        calibration-result.json
             |                         |
        Player.live()              record()
             |                         |
       latest BGR pair      two H.264 tracks + embedded calibration
                                       |
                                  Player.mp4()
                                       |
camera0/camera1 -> equi_1/equi_2 -> equi_blended -> selected view projection
```

`Player.live()` reads calibration from the JSON file. `Player.mp4()` ignores
external JSON and uses the complete calibration result embedded in the MP4.
Both sources produce the same immutable `FrameBundle` and `PlayerFrame`
contracts.

The core is pull-based and single-consumer. A returned frame is an independent,
read-only BGR snapshot and can be sent to another thread, queue, web handler, or
platform adapter. Live capture keeps only the latest complete camera pair, so a
slow preview does not build an unbounded queue.

Stitching is lazy. Changing yaw, pitch, roll, FOV, or projection renders another
view from the cached blended panorama instead of remapping both fisheye images
again.

The renderer preserves the proven Mapper row-vector convention. Do not insert
RGB/BGR conversion inside the core: every public NumPy image is OpenCV-compatible
`uint8` BGR.
