"""Generate the printable A4 checkerboard used by intrinsic calibration."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = A4
    square = 18 * mm
    columns, rows = 10, 7  # 9x6 inner corners
    board_width = columns * square
    board_height = rows * square
    origin_x = (page_width - board_width) / 2
    origin_y = 83 * mm

    canvas = Canvas(str(output), pagesize=A4, pageCompression=1)
    canvas.setTitle("RPI360 9x6 intrinsic calibration checkerboard")
    canvas.setAuthor("Henry Chi")
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    canvas.setFillColorRGB(0, 0, 0)
    for row in range(rows):
        for column in range(columns):
            if (row + column) % 2 == 0:
                canvas.rect(
                    origin_x + column * square,
                    origin_y + row * square,
                    square,
                    square,
                    fill=1,
                    stroke=0,
                )
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(0.5)
    canvas.rect(origin_x, origin_y, board_width, board_height, fill=0, stroke=1)

    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawCentredString(
        page_width / 2,
        235 * mm,
        "RPI360 intrinsic calibration checkerboard",
    )
    canvas.setFont("Helvetica", 10)
    canvas.drawCentredString(
        page_width / 2,
        228 * mm,
        "9 x 6 inner corners | 18 mm squares | A4 portrait",
    )
    canvas.drawCentredString(
        page_width / 2,
        222 * mm,
        "Print at 100% / Actual Size. Disable Fit to Page.",
    )

    ruler_x = (page_width - 100 * mm) / 2
    ruler_y = 45 * mm
    canvas.setLineWidth(1)
    canvas.line(ruler_x, ruler_y, ruler_x + 100 * mm, ruler_y)
    canvas.line(ruler_x, ruler_y - 2 * mm, ruler_x, ruler_y + 2 * mm)
    canvas.line(
        ruler_x + 100 * mm,
        ruler_y - 2 * mm,
        ruler_x + 100 * mm,
        ruler_y + 2 * mm,
    )
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(
        page_width / 2,
        38 * mm,
        "This reference line must measure exactly 100 mm after printing.",
    )
    canvas.showPage()
    canvas.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path("hardware/calibration/checkerboard-9x6-a4.pdf"),
    )
    args = parser.parse_args()
    build(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
