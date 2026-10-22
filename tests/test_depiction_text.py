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

import hashlib
import importlib.util
from pathlib import Path

import pytest

from molmanager.chem import depiction_font_metrics as metrics
from molmanager.chem.depiction_text import cap_height, text_advance, text_ink_bounds

ROOT = Path(__file__).resolve().parent.parent
UPEM = metrics.UNITS_PER_EM
LABELS = ["C", "CH3", "NH2", "H2N", "OH", "Cl", "Br", "Si", "13C", "+", "−", "Na", "*"]


def _font_path() -> Path:
    return ROOT / "molmanager" / "resources" / "fonts" / metrics.FONT_FILE


def test_metrics_table_matches_bundled_font_file():
    digest = hashlib.sha256(_font_path().read_bytes()).hexdigest()
    assert digest == metrics.FONT_SHA256


def test_metrics_table_is_current():
    pytest.importorskip("fontTools")
    spec = importlib.util.spec_from_file_location(
        "build_font_metrics", ROOT / "scripts" / "build_font_metrics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    table = ROOT / "molmanager" / "chem" / "depiction_font_metrics.py"
    assert module.render_module(_font_path()) == table.read_text(encoding="utf-8")


def test_advance_sums_glyph_advances():
    expected = (metrics.GLYPHS["O"][0] + metrics.GLYPHS["H"][0]) / UPEM
    assert text_advance("OH", 1.0) == pytest.approx(expected)
    assert text_advance("OH", 3.0) == pytest.approx(3 * expected)
    assert text_advance("", 1.0) == 0.0


def test_ink_bounds_of_one_glyph_are_its_box():
    _advance, x0, y0, x1, y1 = metrics.GLYPHS["H"]
    assert text_ink_bounds("H", 1.0) == pytest.approx((x0 / UPEM, y0 / UPEM, x1 / UPEM, y1 / UPEM))
    assert text_ink_bounds("  ", 1.0) == (0.0, 0.0, 0.0, 0.0)


def test_ink_bounds_span_the_pen_positions():
    min_x, min_y, max_x, max_y = text_ink_bounds("Cl", 1.0)
    c_advance = metrics.GLYPHS["C"][0]
    assert max_x == pytest.approx((c_advance + metrics.GLYPHS["l"][3]) / UPEM)
    assert min_y < 0 < max_y
    assert min_x > 0


def test_unknown_character_uses_fallback_width():
    assert "\u4e00" not in metrics.GLYPHS
    assert text_advance("\u4e00", 1.0) == pytest.approx(metrics.FALLBACK_ADVANCE / UPEM)
    assert text_ink_bounds("\u4e00", 1.0)[3] == pytest.approx(cap_height(1.0))


def test_qt_draws_the_bundled_font_at_table_widths(qapp):
    from PyQt5.QtGui import QFontInfo, QFontMetricsF

    from molmanager.ui.depiction_font import depiction_label_font

    font = depiction_label_font(UPEM)
    assert QFontInfo(font).family() == metrics.FONT_FAMILY
    measured = QFontMetricsF(font)
    for label in LABELS:
        assert measured.horizontalAdvance(label) == pytest.approx(
            text_advance(label, UPEM), rel=5e-3
        ), label
