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

"""Run every file-operation benchmark and record or compare a baseline.

Cases: app startup, File > Open (FDA SDF, generated 100k SDF and CSV), Save Session
(FDA session, 100k table), and Open Session (FDA session, the saved 100k session).
Each case runs in a fresh process; the reported value is the median over repeats.

Usage:
    python scripts/benchmark_file_ops.py --record            # write benchmarks/baseline.json
    python scripts/benchmark_file_ops.py --compare           # print change vs the baseline
    python scripts/benchmark_file_ops.py --only startup,file_open_fda_sdf --compare
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SAMPLES = ROOT / "samples"
BASELINE = ROOT / "benchmarks" / "baseline.json"
WORK = Path(tempfile.gettempdir()) / "molmanager_bench"

FDA_SDF = SAMPLES / "fda_approved.sdf"
FDA_CMS = SAMPLES / "fda_approved.cms"
BIG_SDF = WORK / "bench_100k.sdf"
BIG_CSV = WORK / "bench_100k.csv"
BIG_CMS = WORK / "bench_100k.cms"

#: Metrics compared per benchmark kind; lower is better for all of them.
METRICS = {
    "startup": ("launch_to_paint_s", "first_paint_s", "import_app_s", "window_build_s"),
    "file_open": (
        "usable_s",
        "visible_drawn_s",
        "all_drawn_s",
        "responsive_s",
        "worst_stall_ms",
        "total_stall_s",
        "peak_rss_mb",
    ),
    "session_open": (
        "usable_s",
        "visible_drawn_s",
        "responsive_s",
        "worst_stall_ms",
        "total_stall_s",
        "peak_rss_mb",
    ),
    "session_save": ("gui_call_s", "total_s", "worst_stall_ms", "bytes"),
}


def _sdf_records(path: Path) -> list[str]:
    """SD records without their ``$$$$`` line; a blank molfile title line is kept."""
    records: list[str] = []
    lines: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.rstrip("\r\n") == "$$$$":
                records.append("".join(lines))
                lines = []
            else:
                lines.append(line.rstrip("\r\n") + "\n")
    return [rec for rec in records if rec.strip()]


def generate_inputs(rows: int) -> None:
    """Write the large SDF and CSV by cycling the FDA set with a unique id per row."""
    WORK.mkdir(parents=True, exist_ok=True)
    if BIG_SDF.is_file() and BIG_CSV.is_file():
        return
    records = _sdf_records(FDA_SDF)
    with BIG_SDF.open("w", encoding="utf-8", newline="\n") as fh:
        for i in range(rows):
            fh.write(records[i % len(records)])
            fh.write(f"> <BENCH_ID>\n{i}\n\n$$$$\n")
    sys.path.insert(0, str(ROOT))
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    smiles = []
    for mol in Chem.ForwardSDMolSupplier(str(FDA_SDF)):
        if mol is not None:
            smiles.append(Chem.MolToSmiles(mol))
    with BIG_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["SMILES", "BENCH_ID", "pIC50", "LogP", "Series"])
        for i in range(rows):
            writer.writerow(
                [
                    smiles[i % len(smiles)],
                    i,
                    f"{5 + (i % 400) / 100:.2f}",
                    f"{i % 7 - 1.5:.1f}",
                    f"S{i % 13}",
                ]
            )


def _cases() -> list[dict]:
    return [
        {"name": "startup", "kind": "startup", "args": []},
        {"name": "file_open_fda_sdf", "kind": "file_open", "args": [str(FDA_SDF)]},
        {"name": "file_open_100k_sdf", "kind": "file_open", "args": [str(BIG_SDF)], "big": True},
        {"name": "file_open_100k_csv", "kind": "file_open", "args": [str(BIG_CSV)], "big": True},
        {
            "name": "session_save_fda",
            "kind": "session_save",
            "args": [str(FDA_CMS), "--out", str(WORK / "fda_saved.cms")],
        },
        {
            "name": "session_save_100k",
            "kind": "session_save",
            "args": [str(BIG_SDF), "--out", str(BIG_CMS)],
            "big": True,
        },
        {"name": "session_open_fda", "kind": "session_open", "args": [str(FDA_CMS)]},
        {"name": "session_open_100k", "kind": "session_open", "args": [str(BIG_CMS)], "big": True},
    ]


_SCRIPT_FOR_KIND = {
    "startup": "benchmark_startup.py",
    "file_open": "benchmark_file_load.py",
    "session_open": "benchmark_session_open.py",
    "session_save": "benchmark_session_save.py",
}


def run_once(case: dict, timeout_s: float) -> dict | None:
    out_json = WORK / f"{case['name']}.json"
    out_json.unlink(missing_ok=True)
    cmd = [sys.executable, str(SCRIPTS / _SCRIPT_FOR_KIND[case["kind"]]), *case["args"]]
    cmd += ["--json", str(out_json)]
    launch_ns = time.time_ns()
    try:
        subprocess.run(
            cmd,
            cwd=ROOT,
            timeout=timeout_s,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"  {case['name']}: timed out after {timeout_s:.0f}s")
        return None
    if not out_json.is_file():
        print(f"  {case['name']}: no result (the benchmark process failed)")
        return None
    result = json.loads(out_json.read_text(encoding="utf-8"))
    if case["kind"] == "startup" and result.get("first_paint_wall_ns"):
        result["launch_to_paint_s"] = round((result["first_paint_wall_ns"] - launch_ns) / 1e9, 4)
    return result


def _median(values: list) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(nums), 4) if nums else None


def run_cases(cases: list[dict], repeats: int, big_repeats: int, timeout_s: float) -> dict:
    summary: dict[str, dict] = {}
    for case in cases:
        n = big_repeats if case.get("big") else repeats
        runs = []
        for i in range(n):
            print(f"{case['name']} run {i + 1}/{n} ...", flush=True)
            result = run_once(case, timeout_s)
            if result is not None:
                runs.append(result)
        medians = {m: _median([r.get(m) for r in runs]) for m in METRICS[case["kind"]]}
        medians["runs"] = len(runs)
        medians["rows"] = runs[-1].get("rows") if runs else None
        summary[case["name"]] = medians
        print(f"  {json.dumps(medians)}", flush=True)
    return summary


def print_comparison(baseline: dict, current: dict) -> None:
    print()
    print(f"{'case':<22} {'metric':<18} {'baseline':>12} {'now':>12} {'change':>9}")
    print("-" * 77)
    for name, now in current.items():
        before = baseline.get("cases", {}).get(name, {})
        for metric, value in now.items():
            if metric in ("runs", "rows"):
                continue
            old = before.get(metric)
            if isinstance(old, (int, float)) and isinstance(value, (int, float)) and old:
                change = f"{(value - old) / old * 100:+.0f}%"
            elif old is None and value is not None:
                change = "new"
            else:
                change = ""
            print(f"{name:<22} {metric:<18} {_fmt(old):>12} {_fmt(value):>12} {change:>9}")


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true", help="write benchmarks/baseline.json")
    mode.add_argument("--compare", action="store_true", help="compare against the baseline")
    ap.add_argument("--only", default="", help="comma-separated case names")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--big-repeats", type=int, default=1)
    ap.add_argument("--rows", type=int, default=100_000, help="rows in the generated inputs")
    ap.add_argument("--timeout-s", type=float, default=900.0)
    ap.add_argument("--save", default=None, help="also write this run's medians to a file")
    args = ap.parse_args()

    generate_inputs(args.rows)
    cases = _cases()
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        cases = [c for c in cases if c["name"] in wanted]
    current = run_cases(cases, args.repeats, args.big_repeats, args.timeout_s)
    record = {
        "recorded": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "cases": current,
    }
    if args.save:
        Path(args.save).write_text(json.dumps(record, indent=2), encoding="utf-8")
    if args.record:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        merged = record
        if args.only and BASELINE.is_file():
            merged = json.loads(BASELINE.read_text(encoding="utf-8"))
            merged.setdefault("cases", {}).update(current)
        BASELINE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        print(f"\nBaseline written to {BASELINE}")
        return
    if not BASELINE.is_file():
        print("No baseline yet; run with --record first.")
        return
    print_comparison(json.loads(BASELINE.read_text(encoding="utf-8")), current)


if __name__ == "__main__":
    main()
