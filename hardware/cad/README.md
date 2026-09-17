# Printable enclosure

The validated enclosure is split into:

- [`top-half.stl`](top-half.stl), approximately 60.0 x 113.8 x 5.0 mm;
- [`bottom-half.stl`](bottom-half.stl), approximately
  60.0 x 113.8 x 41.0 mm.

STL files do not encode a unit. Import both files as **millimetres** and confirm
these bounding dimensions in the slicer before printing. Do not automatically
scale either half independently.

![CAD overview](../photos/cad-overview.png)

## Fastener interfaces

This revision was built around:

- M2 heat-set inserts with M2 thread and 2 mm insert length;
- M2 x 4 mm screws for the camera PCBs;
- M3 heat-set inserts with M3 thread and 3 mm insert length;
- M3 x 6 mm screws for the main enclosure joint.

Heat-set insert outside diameter and knurl geometry are not standardized by the
M2/M3 thread designation. Compare the exact inserts with the modeled pockets
and make a small test print before committing to the complete enclosure.

The power-bank opening is measured for Henry Chi's existing unit. A different
power bank is not expected to fit without modifying the CAD. The tripod
interface shown in the photographs is separate from the listed M2/M3 enclosure
fasteners; verify compatibility with the intended tripod or adapter.

## License status

Copyright (c) 2026 Henry Chi.

These enclosure models are open hardware licensed under the
[CERN Open Hardware Licence Version 2 - Permissive](LICENSE)
(`CERN-OHL-P-2.0`). See [`NOTICE`](NOTICE) for the exact Covered Source and
design-specific notice.
