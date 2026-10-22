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

"""Measure the per-row cost of the Structure column's PNG depictions.

For one sample file this reports RDKit draw time per molecule in a single process, PNG bytes
per row, GUI-thread decode time through the table's own decode path, and the time to blit a
decoded pixmap into a cell. With ``--session`` it also reads that session's ``.mctcache``
sidecar and reports the bytes it stores per row. These are the baselines the vector depiction
work is measured against; ``scripts/benchmark_render2d.py`` covers process-pool throughput.

Usage:
    python scripts/benchmark_depiction.py samples/fda_approved.sdf
        [--limit N] [--session samples/fda_approved.cms] [--json OUT]
"""

from __future__ import annotations

import argparse
import os
import platform
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bench_common import emit_result  # noqa: E402
from depiction_samples import load_depiction_samples, rdkit_release_ok, summarize  # noqa: E402

from molmanager.chem.structure_2d_depiction import render_molecule_png  # noqa: E402
from molmanager.table.structure_depiction_layout import (  # noqa: E402
    structure_depict_height,
    structure_depict_width,
)


def _measure_draw(mols, width: int, height: int) -> tuple[list[bytes], list[float]]:
    pngs: list[bytes] = []
    draw_ms: list[float] = []
    for mol in mols:
        t0 = time.perf_counter()
        try:
            png = render_molecule_png(mol, width, height)
        except Exception:  # noqa: BLE001 — a failed row is reported as missing, not fatal
            png = b""
        draw_ms.append((time.perf_counter() - t0) * 1000.0)
        pngs.append(png)
    return pngs, draw_ms


def _measure_decode_and_blit(
    pngs: list[bytes], width: int, height: int
) -> tuple[list[float], list[float]]:
    from PyQt5.QtGui import QImage, QPainter

    from molmanager.ui.structure_pixmap import pixmap_from_structure_render_png

    decode_ms: list[float] = []
    blit_us: list[float] = []
    cell = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(cell)
    try:
        for png in pngs:
            if not png:
                continue
            t0 = time.perf_counter()
            pixmap = pixmap_from_structure_render_png(png, width, height)
            decode_ms.append((time.perf_counter() - t0) * 1000.0)
            t0 = time.perf_counter()
            painter.drawPixmap(0, 0, pixmap)
            blit_us.append((time.perf_counter() - t0) * 1e6)
    finally:
        painter.end()
    return decode_ms, blit_us


def _sidecar_stats(session_path: str, width: int, height: int) -> dict:
    from molmanager.storage.session_structure_cache import (
        read_structure_cache,
        session_cache_path,
    )

    cache_path = session_cache_path(session_path)
    loaded = read_structure_cache(session_path, depict_width=width, depict_height=height)
    if loaded is None:
        return {"path": str(cache_path), "usable": False}
    _header, raw = loaded
    fd, tmp_name = tempfile.mkstemp(prefix="molmanager_bench_", suffix=".sqlite")
    os.close(fd)
    try:
        with open(tmp_name, "wb") as fh:
            fh.write(raw)
        conn = sqlite3.connect(tmp_name)
        try:
            rows, avg_bytes, max_bytes = conn.execute(
                "SELECT COUNT(*), AVG(LENGTH(blob)), MAX(LENGTH(blob)) FROM pngs"
            ).fetchone()
        finally:
            conn.close()
    finally:
        os.remove(tmp_name)
    return {
        "path": str(cache_path),
        "usable": True,
        "file_mb": round(cache_path.stat().st_size / (1024 * 1024), 2),
        "rows": int(rows or 0),
        "bytes_per_row_mean": round(float(avg_bytes or 0.0), 1),
        "bytes_per_row_max": int(max_bytes or 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", help="SDF / SD / molfile, or a smiles/name/category TSV")
    ap.add_argument("--limit", type=int, default=2000, help="molecules to measure (0 = all)")
    ap.add_argument("--session", help="session file whose .mctcache sidecar to measure")
    ap.add_argument("--json", help="also write the result to this JSON path")
    args = ap.parse_args()

    from PyQt5.QtCore import QT_VERSION_STR
    from PyQt5.QtWidgets import QApplication
    from rdkit import __version__ as rdkit_version

    app = QApplication.instance() or QApplication(sys.argv[:1])
    width, height = int(structure_depict_width()), int(structure_depict_height())
    samples = load_depiction_samples(args.path, args.limit)
    if not rdkit_release_ok():
        print(f"warning: RDKit {rdkit_version} is older than the project requires", file=sys.stderr)

    pngs, draw_ms = _measure_draw([s.mol for s in samples], width, height)
    decode_ms, blit_us = _measure_decode_and_blit(pngs, width, height)
    sizes = [float(len(png)) for png in pngs if png]
    result = {
        "input": os.path.abspath(args.path),
        "molecules": len(samples),
        "failed_draws": sum(1 for png in pngs if not png),
        "depict_size": [width, height],
        "screen_device_pixel_ratio": float(app.primaryScreen().devicePixelRatio()),
        "environment": {
            "rdkit": rdkit_version,
            "rdkit_release_ok": rdkit_release_ok(),
            "qt": QT_VERSION_STR,
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "draw_ms_per_molecule": summarize(draw_ms),
        "png_bytes_per_row": summarize(sizes, digits=1),
        "png_total_mb": round(sum(sizes) / (1024 * 1024), 2),
        "decode_ms_per_row": summarize(decode_ms),
        "blit_us_per_row": summarize(blit_us, digits=1),
    }
    if args.session:
        result["sidecar"] = _sidecar_stats(args.session, width, height)
    emit_result(result, args.json)


if __name__ == "__main__":
    main()
