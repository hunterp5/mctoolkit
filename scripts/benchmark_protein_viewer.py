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

"""Benchmark Protein Viewer restore from a .cms (default: FDA approved session).

Usage:
    python scripts/benchmark_protein_viewer.py
    python scripts/benchmark_protein_viewer.py samples/fda_approved_physprops.cms --runs 3
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

configure_qtwebengine_quiet_logs()
try:
    import PyQt5.QtWebEngineWidgets  # noqa: F401
except Exception:
    pass

from PyQt5.QtWidgets import QApplication

from molmanager.protein.hydrogen_bonds import detect_hydrogen_bonds
from molmanager.protein.protein_interactions import (
    compute_viewer_interaction_overlays,
    detect_prolif_interactions,
    prolif_available,
)
from molmanager.protein.structure_atoms import parse_structure_atoms, pocket_view_plan
from molmanager.protein.structure_cif import _parse_cif_loops, cif_viewer_bond_tables
from molmanager.protein.structure_inventory import (
    parse_polymer_sequences,
    parse_structure_components,
)
from molmanager.table.session_v4 import read_session_v4
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.protein_embed import ProteinEmbedView
from molmanager.ui.protein_viewer import ProteinViewerDialog


def _session_document(cms_path: Path) -> dict:
    """The session's manifest and sidecars; row and store files are discarded."""
    opened = read_session_v4(cms_path)
    opened.discard_temp_files()
    return opened.manifest


def _ms(fn, *, n: int = 1, warmup: bool = True) -> tuple[list[float], object]:
    out = None
    if warmup:
        out = fn()
    times: list[float] = []
    for _ in range(max(1, n)):
        t0 = time.perf_counter()
        out = fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times, out


def _print_ms(label: str, times: list[float], extra: str = "") -> None:
    if not times:
        return
    extra_s = f"  {extra}" if extra else ""
    if len(times) == 1:
        print(f"  {label:32s} {times[0]:8.1f} ms{extra_s}", flush=True)
        return
    print(
        f"  {label:32s} min={min(times):7.1f}  "
        f"med={statistics.median(times):7.1f}  max={max(times):7.1f} ms{extra_s}",
        flush=True,
    )


def _ligand_keys(rows: list) -> list[tuple[str, str, str, str]]:
    keys = []
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != "ligand":
            continue
        keys.append(
            (
                str(row.get("chain") or ""),
                str(row.get("resn") or ""),
                str(row.get("resi") or ""),
                str(row.get("icode") or ""),
            )
        )
    return keys


def _bench_parse(text: str, fmt: str, rows: list, repeats: int) -> None:
    print("\nParse / overlay kernels (no Qt canvas)", flush=True)
    times, comps = _ms(lambda: parse_structure_components(text, fmt), n=1, warmup=False)
    _print_ms("parse_structure_components", times, extra=f"n={len(comps or ())}")
    times, chains = _ms(lambda: parse_polymer_sequences(text, fmt), n=1, warmup=False)
    _print_ms("parse_polymer_sequences", times, extra=f"chains={len(chains or ())}")
    times, _loops = _ms(lambda: _parse_cif_loops(text), n=repeats, warmup=True)
    _print_ms("_parse_cif_loops (cached)", times)
    times, bonds = _ms(lambda: cif_viewer_bond_tables(text), n=repeats)
    _print_ms("cif_viewer_bond_tables", times, extra=f"comps={len(bonds or {})}")
    times, atoms = _ms(lambda: parse_structure_atoms(text, fmt), n=repeats)
    _print_ms("parse_structure_atoms", times, extra=f"n={len(atoms or ())}")
    times, hbonds = _ms(lambda: detect_hydrogen_bonds(text, fmt), n=1, warmup=False)
    _print_ms("detect_hydrogen_bonds", times, extra=f"n={len(hbonds or ())}")
    lig = _ligand_keys(rows)
    times, plan = _ms(
        lambda: pocket_view_plan(text, fmt, ligand_keys=lig or None), n=1, warmup=False
    )
    _print_ms("pocket_view_plan", times, extra="ok" if plan else "none")
    if prolif_available():
        times, contacts = _ms(lambda: detect_prolif_interactions(text, fmt), n=1, warmup=False)
        _print_ms("detect_prolif_interactions", times, extra=f"n={len(contacts or ())}")
        times, pair = _ms(
            lambda: compute_viewer_interaction_overlays(text, fmt),
            n=1,
            warmup=False,
        )
        hb, pr = pair or ((), ())
        _print_ms("compute_viewer_interaction_overlays", times, extra=f"h={len(hb)} p={len(pr)}")
    else:
        print("  detect_prolif_interactions            skipped (ProLIF not installed)", flush=True)


def _bench_viewer_restore(state: dict, runs: int) -> None:
    print("\nProtein Viewer apply_session_state (WebEngine skipped)", flush=True)
    first_ms: list[float] = []
    n_slots = 0
    for _ in range(runs):
        dlg = ProteinViewerDialog()
        t0 = time.perf_counter()
        dlg.apply_session_state(state)
        first_ms.append((time.perf_counter() - t0) * 1000.0)
        n_slots = len(getattr(dlg, "_slots", []) or [])
        dlg._suppress_close_prompt = True
        dlg.close()
    _print_ms("apply_session_state (first paint)", first_ms, extra=f"slots={n_slots}")


def _bench_open_from_app(cms_path: Path) -> None:
    print("\nOpen Protein Viewer after session payload is in memory", flush=True)
    app = ChemistryWorkspaceWindow()
    try:
        app._try_auto_render_all_structures_after_ingest = lambda: False
        t0 = time.perf_counter()
        doc = _session_document(cms_path)
        decode_ms = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        app._restore_protein_viewer(doc.get("protein_viewer"))
        stash_ms = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        dlg = app.open_protein_viewer()
        open_ms = (time.perf_counter() - t0) * 1000.0
        qapp = QApplication.instance()
        if qapp is not None:
            for _ in range(30):
                qapp.processEvents()
                if dlg is not None and getattr(dlg, "_slots", None):
                    break
        n_slots = len(getattr(dlg, "_slots", []) or []) if dlg is not None else 0
        print(f"  {'session decode (full cms)':32s} {decode_ms:8.1f} ms", flush=True)
        print(f"  {'stash protein_viewer payload':32s} {stash_ms:8.1f} ms", flush=True)
        print(f"  {'open_protein_viewer':32s} {open_ms:8.1f} ms  slots={n_slots}", flush=True)
        if dlg is not None:
            dlg._suppress_close_prompt = True
            dlg.close()
    finally:
        try:
            app.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Protein Viewer session load.")
    parser.add_argument(
        "cms",
        nargs="?",
        default="samples/fda_approved_physprops.cms",
        help="Session file (default: samples/fda_approved_physprops.cms)",
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--parse-repeats", type=int, default=3)
    args = parser.parse_args()
    cms_path = Path(args.cms).expanduser()
    if not cms_path.is_file():
        raise SystemExit(f"Session file not found: {cms_path}")

    _qapp = QApplication.instance() or QApplication([])
    ProteinEmbedView._ensure_web = lambda self: None  # type: ignore[method-assign]
    t0 = time.perf_counter()
    doc = _session_document(cms_path)
    decode_ms = (time.perf_counter() - t0) * 1000.0
    pv = doc.get("protein_viewer")
    print(f"CMS: {cms_path}  ({cms_path.stat().st_size / (1024 * 1024):.1f} MB)", flush=True)
    print(f"  decode document                 {decode_ms:8.1f} ms", flush=True)
    if not isinstance(pv, dict) or not pv.get("structures"):
        raise SystemExit("No protein_viewer structures in that session.")
    structs = pv.get("structures") or []
    print(f"  protein_viewer structures       {len(structs)}", flush=True)
    text = str(structs[0].get("text") or "")
    fmt = str(structs[0].get("fmt") or "pdb")
    print(
        f"  first structure                 {structs[0].get('name')}  {fmt}  {len(text):,} chars",
        flush=True,
    )
    print(f"  hbonds                          {pv.get('hbonds')}", flush=True)
    print(f"  interactions                    {pv.get('interactions')}", flush=True)
    print(f"  pocket                          {bool(pv.get('pocket'))}", flush=True)

    _bench_parse(text, fmt, list(structs[0].get("rows") or []), max(1, args.parse_repeats))
    _bench_viewer_restore(pv, max(1, args.runs))
    _bench_open_from_app(cms_path)


if __name__ == "__main__":
    main()
