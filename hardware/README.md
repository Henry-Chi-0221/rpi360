# Hardware

## Validated build

The reference build uses:

- Raspberry Pi 5 with 8 GB RAM.
- Two [Arducam B0287 wide-angle Sony IMX219 modules](https://www.arducam.com/arducam-imx219-wide-angle-camera-module-for-nvidia-jetson-raspberry-pi-compute-module-4-3-3-b0287.html).
- Two correct camera ribbon cables for the Raspberry Pi 5 CAM/DISP connectors.
- A custom modeled and 3D-printed rigid frame.
- A high-quality microSD card with sufficient space for two simultaneous streams.
- A reliable 5 V / 5 A supply. The
  [official Raspberry Pi 27 W USB-C supply](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply)
  is the safest reference.

The printed enclosure has a dedicated opening measured for Henry Chi's existing
phone power bank. It is a one-off mechanical fit: power banks with different
dimensions will not fit that opening. Treat the enclosure dimensions as
specific to the validated build, not as a universal power-bank mount.

## Rig geometry

The lenses must be mounted back-to-back with their optical axes approximately
180 degrees apart. Keep the lens centers as close together as the boards allow,
and make the assembly rigid enough that pressing a cable or moving the power
bank cannot change the camera-to-camera rotation.

Exact alignment is not required: rig calibration measures the remaining
rotation. Mechanical movement after calibration is not allowed. Re-run both
calibration stages after changing a camera, lens focus, board position, ribbon
cable routing, or the printed mount.

Keep the case, Pi, cables, and the fitted power bank outside as much of each
circular image as possible. A small unavoidable rig footprint can be hidden at
the nadir, but large obstructions reduce overlap and SIFT matches.

## Camera identity

Logical camera 0 and camera 1 must stay connected to the same physical lenses.
Before calibration:

```bash
rpicam-hello --list-cameras
```

If the camera order changes, restore the connections or recalibrate. RPI360
records the logical camera mapping as MP4 track IDs 1 and 2.

## Printable calibration board

Print [`checkerboard-9x6-a4.pdf`](calibration/checkerboard-9x6-a4.pdf) at
**100% / Actual Size** with all page fitting disabled. Confirm that its
reference line measures exactly 100 mm. The pattern has 9 x 6 inner corners and
18 mm squares.

Mount it to a flat surface. A warped sheet produces biased intrinsics.

## CAD status

The original custom CAD is not included yet. `hardware/cad/` is intentionally
reserved for the future STL/STEP/3MF files. Any future model must name the exact
power-bank model and measured dimensions it targets. Until those files are
published, this document describes the optical and structural requirements but
does not claim that the exact physical frame is reproducible.
