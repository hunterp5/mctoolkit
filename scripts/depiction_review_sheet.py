# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Render a molecule set into one labelled image grid for visual review.

Each cell is drawn by the table's PNG renderer at the table's depiction size (times
``--scale``), with the molecule's name and category underneath. Sheets from this script are
the reference that later depiction renderers are compared against side by side.

Usage:
    python scripts/depiction_review_sheet.py tests/data/depiction_golden.tsv --out review.png
        [--columns 8] [--limit N] [--scale 2]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from depiction_samples import load_depiction_samples, rdkit_release_ok  # noqa: E402

from molmanager.chem.structure_2d_depiction import render_molecule_png  # noqa: E402
from molmanager.table.structure_depiction_layout import (  # noqa: E402
    structure_depict_height,
    structure_depict_width,
)

_CAPTION_LINES = 2
_GRID_LINE = 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", help="SDF / SD / molfile, or a smiles/name/category TSV")
    ap.add_argument("--out", required=True, help="PNG path for the sheet")
    ap.add_argument("--columns", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="molecules to include (0 = all)")
    ap.add_argument("--scale", type=int, default=1, help="cell size multiple, e.g. 2 for zoom")
    args = ap.parse_args()

    from PyQt5.QtCore import QRect, Qt
    from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
    from PyQt5.QtWidgets import QApplication
    from rdkit import __version__ as rdkit_version

    _app = QApplication.instance() or QApplication(sys.argv[:1])
    samples = load_depiction_samples(args.path, args.limit)
    if not samples:
        raise SystemExit(f"no molecules read from {args.path}")

    scale = max(1, int(args.scale))
    cell_w = int(structure_depict_width()) * scale
    cell_h = int(structure_depict_height()) * scale
    font = QFont()
    font.setPointSize(8)
    caption_h = QFontMetrics(font).lineSpacing() * _CAPTION_LINES + 4
    columns = max(1, min(int(args.columns), len(samples)))
    rows = (len(samples) + columns - 1) // columns
    header_h = QFontMetrics(font).lineSpacing() + 8
    pitch_w = cell_w + _GRID_LINE
    pitch_h = cell_h + caption_h + _GRID_LINE

    sheet = QImage(columns * pitch_w, header_h + rows * pitch_h, QImage.Format_RGB32)
    sheet.fill(QColor(255, 255, 255))
    painter = QPainter(sheet)
    try:
        painter.setFont(font)
        painter.setPen(QColor(90, 90, 90))
        title = (
            f"{os.path.basename(args.path)} · {len(samples)} molecules · "
            f"{cell_w}x{cell_h} px · RDKit {rdkit_version}"
            + ("" if rdkit_release_ok() else " (older than the project requires)")
        )
        painter.drawText(QRect(6, 0, sheet.width() - 12, header_h), Qt.AlignVCenter, title)
        for index, sample in enumerate(samples):
            x = (index % columns) * pitch_w
            y = header_h + (index // columns) * pitch_h
            try:
                png = render_molecule_png(sample.mol, cell_w, cell_h)
            except Exception:  # noqa: BLE001 — show the failure in the sheet instead
                png = b""
            image = QImage.fromData(png) if png else QImage()
            if image.isNull():
                painter.setPen(QColor(200, 40, 40))
                painter.drawText(QRect(x, y, cell_w, cell_h), Qt.AlignCenter, "draw failed")
            else:
                painter.drawImage(x, y, image)
            painter.setPen(QColor(60, 60, 60))
            caption = sample.name if not sample.category else f"{sample.name}\n{sample.category}"
            painter.drawText(
                QRect(x + 4, y + cell_h, cell_w - 8, caption_h),
                int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap),
                caption,
            )
        painter.setPen(QColor(225, 225, 225))
        for col in range(1, columns):
            painter.drawLine(col * pitch_w - 1, header_h, col * pitch_w - 1, sheet.height())
        for row in range(1, rows):
            line_y = header_h + row * pitch_h - 1
            painter.drawLine(0, line_y, sheet.width(), line_y)
    finally:
        painter.end()

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    if not sheet.save(args.out):
        raise SystemExit(f"could not write {args.out}")
    print(f"wrote {args.out} ({len(samples)} molecules, {columns}x{rows} grid)")


if __name__ == "__main__":
    main()
