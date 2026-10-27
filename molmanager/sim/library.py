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

"""Apply one simulation document to many pocket poses and replicates."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .document import STAGE_DYNAMICS, STAGE_CUSTOM, DynamicsStage, SimulationDocument, Stage
from .protocol import length_to_steps

# One nanosecond of summed production is enough to ask before a queue starts.
CONFIRM_ABOVE_NS = 1.0


@dataclass(frozen=True)
class PoseRow:
    """One table row whose 3D pose is already in the pocket."""

    oid: int
    label: str
    pose_path: str
    status: str = "pending"


def production_length_ps(document: SimulationDocument) -> float:
    """Sum of enabled dynamics and custom stages, in picoseconds."""
    total = 0.0
    for stage in document.stages:
        if not stage.enabled:
            continue
        total += _stage_ps(stage)
    return total


def library_cost_message(n_ligands: int, n_replicates: int, production_ps: float) -> str:
    """Human summary of ligand count × replicates × production length."""
    per_ns = production_ps / 1000.0
    total_ns = n_ligands * n_replicates * per_ns
    return (
        f"{n_ligands} ligands × {n_replicates} replicates × {per_ns:.2f} ns "
        f"= {total_ns:.2f} ns of production."
    )


def library_needs_confirmation(
    n_ligands: int,
    n_replicates: int,
    production_ps: float,
    *,
    threshold_ns: float = CONFIRM_ABOVE_NS,
) -> bool:
    """True when the queue is longer than *threshold_ns* of summed production."""
    total_ns = n_ligands * n_replicates * production_ps / 1000.0
    return total_ns > threshold_ns


def summarize_replicates(rows: list[dict]) -> list[dict]:
    """Mean and sample standard deviation of ``value`` for each ``oid``."""
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[int(row["oid"])].append(row)
    summary: list[dict] = []
    for oid, items in grouped.items():
        values = [float(item["value"]) for item in items if item.get("value") is not None]
        finite = [value for value in values if value == value]
        mean = sum(finite) / len(finite) if finite else float("nan")
        if len(finite) > 1:
            var = sum((value - mean) ** 2 for value in finite) / (len(finite) - 1)
            sd = math.sqrt(var)
        else:
            sd = 0.0 if finite else float("nan")
        status = "ok" if all(item.get("status") == "ok" for item in items) else "failed"
        if any(item.get("status") == "cancelled" for item in items):
            status = "cancelled"
        summary.append(
            {
                "oid": oid,
                "label": items[0].get("label") or "",
                "status": status,
                "n": len(items),
                "mean": mean,
                "sd": sd,
                "text": _summary_text(status, mean, sd, len(items)),
            }
        )
    return summary


def _summary_text(status: str, mean: float, sd: float, n: int) -> str:
    if status != "ok" or mean != mean:
        return status
    if n <= 1 or sd != sd:
        return f"{mean:.3g}"
    return f"{mean:.3g} ± {sd:.3g}"


def _stage_ps(stage: Stage) -> float:
    if isinstance(stage, DynamicsStage) or type(stage).__name__ == "CustomStage":
        steps = length_to_steps(stage.length_value, stage.length_unit, stage.timestep_fs)
        return steps * float(stage.timestep_fs) / 1000.0
    if getattr(stage, "kind", "") in {STAGE_DYNAMICS, STAGE_CUSTOM}:
        steps = length_to_steps(stage.length_value, stage.length_unit, stage.timestep_fs)
        return steps * float(stage.timestep_fs) / 1000.0
    return 0.0
