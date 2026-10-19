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

"""Substructure SMARTS matching and async job plumbing."""

from __future__ import annotations

import logging

from ...chem.molecule_conversion import mol_to_canonical_smiles
from ..background_jobs import unregister_background_job
from .cards import SubstructureFilterCard

logger = logging.getLogger(__name__)


class FilterSubstructureMixin:
    """SMARTS card matching, including ``SubstructureFilterWorker`` jobs."""

    def _clear_filter_target_smiles_cache(self) -> None:
        """Drop cached MolToSmiles results (e.g. after wholesale ``mols`` replacement)."""
        self._filter_target_smiles_cache = None
        self._substructure_target_mol_cache = {}

    def _smiles_for_substructure_target(self, oid: int, mol) -> str:
        """Stable SMILES string for filter worker targets; cache per (oid, mol object id)."""
        if mol is None:
            return ""
        cache = getattr(self, "_filter_target_smiles_cache", None)
        if cache is None:
            cache = {}
            self._filter_target_smiles_cache = cache
        mid = id(mol)
        t = cache.get(oid)
        if t is not None and t[0] == mid:
            return t[1]
        smi = mol_to_canonical_smiles(mol)
        cache[oid] = (mid, smi)
        return smi

    def _substructure_filter_targets(
        self, structure_source: str = "Structure"
    ) -> list[tuple[int, bytes | str]]:
        """``(oid, blob_or_text)`` per row for ``SubstructureFilterWorker``.

        Stored blobs / cell text only; the worker rebuilds molecules so filtering a large
        table does not hydrate every row on the GUI thread.
        """
        src = (structure_source or "Structure").strip() or "Structure"
        if src != "Structure" and src not in self.headers:
            return []
        return [
            (int(p.oid), p.blob or p.smiles)
            for p in self.collect_scoped_table_structure_payloads(src)
        ]

    def _mol_for_substructure_filter_row(self, row: int, structure_source: str):
        """Molecule used when evaluating a substructure filter card on *row*."""
        oid = int(self._table_model.row_oid(row))
        src = (structure_source or "Structure").strip() or "Structure"
        resolve = getattr(self, "_mol_for_structure_tool_oid", None)
        if callable(resolve):
            return resolve(oid, src)
        if src == "Structure":
            return (getattr(self, "mols", None) or {}).get(oid)
        return None

    def _substructure_override_matches_card(
        self,
        card: SubstructureFilterCard,
        override_smarts: str | None,
        override_source: str | None,
    ) -> bool:
        if override_smarts is None:
            return False
        if override_smarts != (card.smarts_edit.text() or "").strip():
            return False
        if override_source is not None and override_source != card.structure_source():
            return False
        return True

    def _normalize_substructure_overrides(
        self, substructure_matches
    ) -> list[tuple[str, str | None, frozenset]]:
        """Normalize async job payload to ``[(smarts, source, oids), ...]``."""
        if not substructure_matches:
            return []
        if isinstance(substructure_matches, list):
            out: list[tuple[str, str | None, frozenset]] = []
            for item in substructure_matches:
                if not item:
                    continue
                if isinstance(item, frozenset):
                    continue
                if len(item) >= 3:
                    smarts, source, oids = item[0], item[1], item[2]
                else:
                    smarts, oids = item[0], item[1]
                    source = "Structure"
                if not isinstance(oids, frozenset):
                    oids = frozenset(oids or ())
                out.append((str(smarts or ""), source, oids))
            return out
        smarts, source, oids = self._unpack_substructure_matches(substructure_matches)
        if smarts is None or oids is None:
            return []
        return [(smarts, source, oids)]

    def _override_for_substructure_card(
        self,
        card: SubstructureFilterCard,
        overrides: list[tuple[str, str | None, frozenset]],
    ) -> frozenset | None:
        for smarts, source, oids in overrides:
            if self._substructure_override_matches_card(card, smarts, source):
                return oids
        return None

    def _unregister_substructure_background_job(self, job_gen: int) -> None:
        job_id = getattr(self, "_substructure_bg_job_id", None)
        if job_id == f"substructure-{job_gen}":
            unregister_background_job(self, job_id)
            self._substructure_bg_job_id = None

    def _cancel_substructure_filter_job(self) -> None:
        """Processes Cancel: discard the in-flight substructure filter job."""
        job_id = getattr(self, "_substructure_bg_job_id", None)
        gen = int(getattr(self, "_substructure_job_gen", 0))
        self._invalidate_substructure_async_jobs()
        if job_id is not None:
            unregister_background_job(self, job_id)
            self._substructure_bg_job_id = None
        elif gen:
            self._unregister_substructure_background_job(gen)
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Filtering substructure", status_message="Substructure filter cancelled.")

    def _on_substructure_filter_finished(self, job_gen: int, matched) -> None:
        self._unregister_substructure_background_job(job_gen)
        if job_gen != getattr(self, "_substructure_job_gen", 0):
            return
        dispatched_queries = list(getattr(self, "_substructure_job_queries", None) or [])
        ss_cards = [
            f for f in self.filters if isinstance(f, SubstructureFilterCard) and f.filter_enabled()
        ]
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Filtering substructure", status_message=None)

        overrides = self._normalize_substructure_overrides(matched)
        if not overrides and isinstance(matched, frozenset):
            # Backward-compatible single frozenset payload.
            if len(dispatched_queries) == 1:
                smarts, src = dispatched_queries[0]
                overrides = [(smarts, src, matched)]
            elif len(ss_cards) == 1:
                card = ss_cards[0]
                overrides = [
                    (
                        (card.smarts_edit.text() or "").strip(),
                        card.structure_source(),
                        matched,
                    )
                ]

        if not overrides:
            self._route_filter_apply(None)
            return

        # Re-run if the user changed SMARTS/source while the job was running.
        for smarts, src, _oids in overrides:
            still = False
            for card in ss_cards:
                if self._substructure_override_matches_card(card, smarts, src):
                    still = True
                    break
            if not still:
                self.apply_filters()
                return

        if len(overrides) == 1:
            smarts, src, oids = overrides[0]
            self._route_filter_apply((smarts, src, oids))
        else:
            self._route_filter_apply(overrides)

    def _on_substructure_filter_failed(self, job_gen: int, msg: str) -> None:
        self._unregister_substructure_background_job(job_gen)
        if job_gen != getattr(self, "_substructure_job_gen", 0):
            return
        logger.warning("Substructure filter job failed: %s", msg)
        self._invalidate_substructure_async_jobs()
        self._route_filter_apply(None)

    def _apply_substructure_override_to_visible(
        self,
        base: frozenset[int],
        override_smarts: str,
        override_oids: frozenset[int],
        *,
        override_source: str | None = None,
    ) -> set[int]:
        for f in self.filters:
            if not isinstance(f, SubstructureFilterCard) or not f.filter_enabled():
                continue
            if not self._substructure_override_matches_card(f, override_smarts, override_source):
                continue
            inv = f.filter_inverted()
            if inv:
                return {oid for oid in base if oid not in override_oids}
            return {oid for oid in base if oid in override_oids}
        return set(base)

    def _apply_substructure_overrides_to_visible(
        self,
        base: frozenset[int] | set[int],
        overrides: list[tuple[str, str | None, frozenset]],
    ) -> set[int]:
        visible = set(base)
        for f in self.filters:
            if not isinstance(f, SubstructureFilterCard) or not f.filter_enabled():
                continue
            oids = self._override_for_substructure_card(f, overrides)
            if oids is None:
                continue
            if f.filter_inverted():
                visible = {oid for oid in visible if oid not in oids}
            else:
                visible = {oid for oid in visible if oid in oids}
        return visible

    def _unpack_substructure_matches(
        self, substructure_matches: tuple | None
    ) -> tuple[str | None, str | None, frozenset | None]:
        """Return ``(smarts, structure_source, matched_oids)`` from a job result tuple."""
        if not substructure_matches:
            return None, None, None
        if len(substructure_matches) >= 3:
            return substructure_matches[0], substructure_matches[1], substructure_matches[2]
        return substructure_matches[0], "Structure", substructure_matches[1]
