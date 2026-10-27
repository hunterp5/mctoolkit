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

"""FASTA helpers and MAFFT multiple-sequence alignment (no Qt)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .structure_components import VALID_SEQUENCE_LETTERS

MISSING_MAFFT_MSG = (
    "MAFFT was not found. Install MAFFT, put it on PATH, copy the all-in-one folder "
    "into molmanager/resources/bin/<platform>/ (Windows: mafft.bat), "
    "or set it under Settings → Configure → MAFFT. "
    "See Help → Protein Sequence."
)

MAFFT_CLI_TIMEOUT_S = 600
_ALIGN_WRAP = 60
_FASTA_ID_RE = re.compile(r"[^\w.|-]+")
_NON_HEADER_SEQ_RE = re.compile(r"^[A-Za-z\-]+$")

MafftRunner = Callable[[list[str], str | None, int], tuple[int, str, str]]


@dataclass(frozen=True)
class FastaRecord:
    """One named amino-acid sequence (ungapped or aligned)."""

    name: str
    sequence: str


def aa_sequence_from_viewer(raw: str) -> str:
    """Uppercase amino-acid letters from a Viewer chain string; drop ``+`` / ``*`` / ``~``."""
    return _letters_from_text(raw, keep_gaps=False)


def _letters_from_text(raw: str, *, keep_gaps: bool) -> str:
    out: list[str] = []
    for ch in raw or "":
        if ch in "+*~" or ch.isspace():
            continue
        if ch == "-":
            if keep_gaps:
                out.append("-")
            continue
        up = ch.upper()
        if up in VALID_SEQUENCE_LETTERS:
            out.append(up)
    return "".join(out)


def fasta_header_id(name: str, *, fallback: str = "seq") -> str:
    """MAFFT-safe FASTA id (no spaces)."""
    text = _FASTA_ID_RE.sub("_", (name or "").strip()).strip("_")
    return text or fallback


def unique_record_name(base: str, existing: set[str]) -> str:
    """Return ``base``, or ``base (2)``, … until unused."""
    label = (base or "seq").strip() or "seq"
    if label not in existing:
        return label
    n = 2
    while f"{label} ({n})" in existing:
        n += 1
    return f"{label} ({n})"


def parse_fasta(text: str) -> list[FastaRecord]:
    """Parse FASTA, or bare sequences separated by blank lines / ``>`` headers."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []
    if ">" in raw:
        return _parse_fasta_headers(raw)
    return _parse_bare_sequences(raw)


def _parse_fasta_headers(text: str) -> list[FastaRecord]:
    records: list[FastaRecord] = []
    name = ""
    chunks: list[str] = []

    def _flush() -> None:
        nonlocal name, chunks
        seq = _letters_from_text("".join(chunks), keep_gaps=True)
        if name or seq:
            records.append(FastaRecord(name=name or f"seq{len(records) + 1}", sequence=seq))
        name = ""
        chunks = []

    for line in text.split("\n"):
        if line.startswith(">"):
            if name or chunks:
                _flush()
            name = line[1:].strip() or f"seq{len(records) + 1}"
            continue
        chunks.append(line.strip())
    if name or chunks:
        _flush()
    return [r for r in records if r.sequence]


def _parse_bare_sequences(text: str) -> list[FastaRecord]:
    records: list[FastaRecord] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        joined = "".join(lines)
        if not _NON_HEADER_SEQ_RE.match(joined.replace(" ", "")):
            continue
        seq = aa_sequence_from_viewer(joined)
        if seq:
            records.append(FastaRecord(name=f"seq{len(records) + 1}", sequence=seq))
    return records


def records_to_fasta(records: list[FastaRecord], *, wrap: int = 60) -> str:
    """Write FASTA; sequences are not re-filtered so aligned gaps are kept."""
    lines: list[str] = []
    width = max(10, int(wrap))
    for rec in records:
        lines.append(f">{rec.name}")
        seq = rec.sequence or ""
        for i in range(0, len(seq), width):
            lines.append(seq[i : i + width])
    return "\n".join(lines) + ("\n" if lines else "")


def mafft_thread_count(requested: int | None = None) -> int:
    """Clamp MAFFT ``--thread`` to 1–8."""
    if requested is None:
        requested = os.cpu_count() or 1
    return max(1, min(8, int(requested)))


def mafft_subprocess_args(
    exe: str,
    fasta_in: Path,
    *,
    threads: int = 1,
) -> tuple[list[str], str | None]:
    """Return ``(argv, cwd)`` for MAFFT. ``cwd`` is the ``.bat`` directory on Windows."""
    flags = ["--auto", "--amino", "--quiet"]
    n_thread = mafft_thread_count(threads)
    if n_thread > 1:
        flags.extend(["--thread", str(n_thread)])
    flags.append(str(fasta_in))
    path = Path(exe)
    if sys.platform.startswith("win") and path.suffix.lower() == ".bat":
        return ["cmd.exe", "/c", str(path), *flags], str(path.parent)
    cwd = str(path.parent) if path.is_file() else None
    return [str(path), *flags], cwd


def record_from_viewer_chain(name: str, sequence: str) -> FastaRecord | None:
    """Map a Viewer polymer chain to an ungapped amino-acid FASTA record."""
    seq = aa_sequence_from_viewer(sequence)
    if not seq:
        return None
    label = (name or "").strip() or "chain"
    return FastaRecord(name=label, sequence=seq)


def run_mafft_alignment(
    records: list[FastaRecord],
    *,
    exe: str,
    timeout_s: int = MAFFT_CLI_TIMEOUT_S,
    threads: int | None = None,
    runner: MafftRunner | None = None,
    cancel_event: threading.Event | None = None,
) -> list[FastaRecord]:
    """Align *records* with MAFFT. *runner* is ``(argv, cwd, timeout_s) -> (code, stdout, stderr)``."""
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Cancelled.")
    usable = [r for r in records if (r.sequence or "").strip()]
    if len(usable) < 2:
        raise ValueError("Need at least two amino-acid sequences to align.")
    exe_path = (exe or "").strip()
    if not exe_path:
        raise RuntimeError(MISSING_MAFFT_MSG)
    id_to_name = {f"s{i + 1}": rec.name for i, rec in enumerate(usable)}
    tagged = [FastaRecord(name=f"s{i + 1}", sequence=rec.sequence) for i, rec in enumerate(usable)]
    n_thread = mafft_thread_count(threads)
    with tempfile.TemporaryDirectory(prefix="molmanager-mafft-") as tmp:
        fasta_in = Path(tmp) / "in.fa"
        fasta_in.write_text(records_to_fasta(tagged), encoding="utf-8")
        argv, cwd = mafft_subprocess_args(exe_path, fasta_in, threads=n_thread)
        if runner is not None:
            code, stdout, stderr = runner(argv, cwd, int(timeout_s))
        else:
            code, stdout, stderr = _run_mafft_popen(
                argv, cwd, int(timeout_s), cancel_event=cancel_event
            )
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Cancelled.")
    if int(code) != 0:
        detail = (stderr or stdout or "").strip() or f"mafft_exit_{code}"
        raise RuntimeError(detail)
    aligned = parse_fasta(stdout)
    if len(aligned) < 2:
        raise RuntimeError("MAFFT did not return an alignment.")
    remapped: list[FastaRecord] = []
    for rec in aligned:
        key = rec.name.split()[0] if rec.name else ""
        remapped.append(FastaRecord(name=id_to_name.get(key, rec.name), sequence=rec.sequence))
    return remapped


def _run_mafft_popen(
    argv: list[str],
    cwd: str | None,
    timeout_s: int,
    *,
    cancel_event: threading.Event | None,
) -> tuple[int, str, str]:
    from ..platform_support.session_runtime import require_tool

    require_tool(argv[0], "MAFFT")
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    limit = max(1, int(timeout_s))
    waited = 0.0
    step = 0.25
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.communicate()
                return 1, "", "Cancelled."
            try:
                stdout, stderr = proc.communicate(timeout=step)
                return int(proc.returncode or 0), stdout or "", stderr or ""
            except subprocess.TimeoutExpired:
                waited += step
                if waited >= limit:
                    proc.kill()
                    proc.communicate()
                    raise TimeoutError(f"MAFFT timed out after {limit} s.") from None
    finally:
        if proc.poll() is None:
            proc.kill()


def pairwise_identity_percent(a: str, b: str) -> float:
    """Percent identity over columns where both sequences have a residue."""
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    match = 0
    compared = 0
    for i in range(n):
        ca, cb = a[i], b[i]
        if ca == "-" or cb == "-":
            continue
        compared += 1
        if ca.upper() == cb.upper():
            match += 1
    if compared == 0:
        return 0.0
    return 100.0 * match / compared


def identity_matrix(records: list[FastaRecord]) -> list[list[float]]:
    """Square pairwise identity matrix (percent)."""
    n = len(records)
    out = [[0.0] * n for _ in range(n)]
    for i, ra in enumerate(records):
        for j, rb in enumerate(records):
            if i == j:
                out[i][j] = 100.0
            else:
                out[i][j] = pairwise_identity_percent(ra.sequence, rb.sequence)
    return out


def format_identity_matrix(records: list[FastaRecord]) -> str:
    """Fixed-width identity table for the Sequence window."""
    if not records:
        return ""
    matrix = identity_matrix(records)
    labels = [fasta_header_id(r.name, fallback=f"seq{i + 1}")[:12] for i, r in enumerate(records)]
    col_w = max(8, max(len(x) for x in labels))
    header = " " * col_w + "".join(f"{lab:>{col_w}}" for lab in labels)
    rows = [header]
    for i, lab in enumerate(labels):
        cells = "".join(f"{matrix[i][j]:{col_w}.1f}" for j in range(len(records)))
        rows.append(f"{lab:<{col_w}}{cells}")
    return "\n".join(rows)


def column_conservation(records: list[FastaRecord]) -> list[str]:
    """Per-column conservation: ``full``, ``majority``, or ``none``."""
    if not records:
        return []
    length = max(len(r.sequence) for r in records)
    out: list[str] = []
    for i in range(length):
        letters = []
        for rec in records:
            if i >= len(rec.sequence):
                continue
            ch = rec.sequence[i]
            if ch != "-":
                letters.append(ch.upper())
        if not letters:
            out.append("none")
            continue
        counts: dict[str, int] = {}
        for ch in letters:
            counts[ch] = counts.get(ch, 0) + 1
        top = max(counts.values())
        if top == len(letters) and len(counts) == 1:
            out.append("full")
        elif top >= max(2, (len(letters) + 1) // 2):
            out.append("majority")
        else:
            out.append("none")
    return out


def clustal_consensus_char(level: str) -> str:
    if level == "full":
        return "*"
    if level == "majority":
        return ":"
    return " "


def records_to_clustal(records: list[FastaRecord], *, wrap: int = _ALIGN_WRAP) -> str:
    """Clustal-style wrapped alignment with a consensus line."""
    if not records:
        return ""
    cons = column_conservation(records)
    length = max((len(r.sequence) for r in records), default=0)
    names = [fasta_header_id(r.name, fallback=f"seq{i + 1}")[:15] for i, r in enumerate(records)]
    name_w = max(10, max(len(n) for n in names))
    width = max(10, int(wrap))
    blocks: list[str] = ["CLUSTAL multiple sequence alignment", ""]
    for start in range(0, length, width):
        end = min(length, start + width)
        for name, rec in zip(names, records, strict=True):
            chunk = (rec.sequence + ("-" * length))[start:end]
            blocks.append(f"{name:<{name_w}} {chunk}")
        marker = "".join(clustal_consensus_char(cons[i]) for i in range(start, end))
        blocks.append(f"{'':<{name_w}} {marker}")
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def alignment_html(records: list[FastaRecord], *, wrap: int = _ALIGN_WRAP) -> str:
    """HTML for a monospace colored MSA (full conservation vs majority vs rest)."""
    if not records:
        return "<p>No alignment.</p>"
    cons = column_conservation(records)
    length = max((len(r.sequence) for r in records), default=0)
    name_w = max(10, max((len(r.name[:18]) for r in records), default=10))
    width = max(10, int(wrap))
    chunks: list[str] = [
        '<pre style="font-family: Consolas, Courier New, monospace; font-size: 13px; '
        'line-height: 1.25; white-space: pre;">'
    ]
    color = {
        "full": "#3cb371",
        "majority": "#daa520",
        "none": "",
    }
    for start in range(0, length, width):
        end = min(length, start + width)
        for rec in records:
            seq = rec.sequence + ("-" * max(0, length - len(rec.sequence)))
            spans: list[str] = []
            for i in range(start, end):
                ch = escape(seq[i])
                level = cons[i] if i < len(cons) else "none"
                if seq[i] == "-":
                    spans.append(f'<span style="color:#888;">{ch}</span>')
                elif color[level]:
                    spans.append(f'<span style="color:{color[level]};">{ch}</span>')
                else:
                    spans.append(ch)
            pad = escape(rec.name[:18].ljust(name_w))
            chunks.append(f"{pad} {''.join(spans)}")
        marker = "".join(
            clustal_consensus_char(cons[i] if i < len(cons) else "none") for i in range(start, end)
        )
        chunks.append(f"{' ' * name_w} {escape(marker)}")
        chunks.append("")
    chunks.append("</pre>")
    return "\n".join(chunks)
