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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Medicinal-chemistry property-space helpers (BOILED-Egg, golden triangle).

Region polygons for the BOILED-Egg plot follow the supporting information of
Daina & Zoete, ChemMedChem 2016 (doi:10.1002/cmdc.201600182), as used in PyBOILEDegg.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors

from ..chem.molecule_conversion import parse_molecule_from_cell_text

# Optional cap from ``MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS``. Unset draws every compound.
_MEDCHEM_PLOT_CAP_MIN = 500
_MEDCHEM_PLOT_CAP_MAX = 2_000_000


class MedChemSpaceCancelled(Exception):
    """Raised when a medchem-space build is cancelled cooperatively."""


def medchem_plot_max_points() -> int | None:
    """Plotly point cap, or ``None`` to draw every compound.

    Region counts and region-select always use the full set. Set
    ``MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS`` to subsample the scatter only.
    """
    raw = (os.environ.get("MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return max(_MEDCHEM_PLOT_CAP_MIN, min(value, _MEDCHEM_PLOT_CAP_MAX))


def snapshot_scope_row_indices(
    row_count: int,
    *,
    only_selected_rows: list[int] | None = None,
    visible_row_indices: list[int] | None = None,
) -> list[int] | None:
    """Source-model rows to scan when building medchem plot snapshots.

    Returns ``None`` when the scope is all source rows ``[0, row_count)`` (no list allocation).
    """
    if only_selected_rows is not None:
        rows = list(only_selected_rows)
        if visible_row_indices is not None:
            visible = frozenset(visible_row_indices)
            rows = [r for r in rows if r in visible]
        return rows
    if visible_row_indices is not None:
        return list(visible_row_indices)
    return None


# GIA (intestinal absorption) and BBB (brain penetration) boundaries — [TPSA, WLOGP].
_GIA_POLYGON: list[tuple[float, float]] = [
    (97.80552243681136, -2.227039047489081),
    (101.88198219217963, -2.1900004937640487),
    (105.83667285876659, -2.1352635055090943),
    (109.65398707923741, -2.063044104609906),
    (113.31885965832892, -1.9736273080479292),
    (116.81682701829244, -1.8673660030685453),
    (120.13408428002757, -1.7446795544963347),
    (123.25753974463277, -1.6060521496937052),
    (126.17486656036041, -1.452030887694577),
    (128.87455137106866, -1.2832236200544374),
    (131.3459397541782, -1.100296551937959),
    (133.57927826881107, -0.903971612911568),
    (135.56575294816514, -0.6950236078172709),
    (137.29752408421504, -0.4742771589719089),
    (138.76775716745777, -0.2426034517596168),
    (139.97064985959926, -0.0009167964611120461),
    (140.90145489273314, 0.2498289801112721),
    (141.556498804638, 0.5086442989322527),
    (141.9331964362546, 0.7745077341799151),
    (142.03006113412775, 1.0463700443367885),
    (141.84671061754818, 1.323158313066756),
    (141.38386848723997, 1.6037801835256746),
    (140.64336136963902, 1.88712816939478),
    (139.628111708033, 2.1720840256232266),
    (138.34212622901268, 2.457523161630431),
    (136.790480129753, 2.7423190795513075),
    (134.97929704852805, 3.025347820008701),
    (132.91572489750854, 3.3054923978675586),
    (130.60790765321815, 3.5816472104649564),
    (128.06495321597865, 3.8527224009187018),
    (125.29689746518848, 4.1176481592945535),
    (122.31466465229157, 4.375378944657261),
    (119.13002428774791, 4.624897611343),
    (115.75554469215258, 4.865219423168597),
    (112.20454339481628, 5.095395939735363),
    (108.49103457556141, 5.314518759490062),
    (104.62967375715677, 5.521723104770812),
    (100.63569996666462, 5.716191234689457),
    (96.52487559396305, 5.8971556723812375),
    (92.313424184794, 6.063902233885377),
    (88.0179664138405, 6.215772846702879),
    (83.6554544905163, 6.352168146908026),
    (79.2431052563408, 6.472549844564003),
    (74.79833223793057, 6.576442848107324),
    (70.3386769237657, 6.663437139317204),
    (65.88173953594848, 6.733189391470147),
    (61.445109570167645, 6.785424324293678),
    (57.04629637799464, 6.8199357903718125),
    (52.7026600654724, 6.836587588714733),
    (48.43134298070782, 6.83531400228186),
    (44.24920206085525, 6.816120057336999),
    (40.17274230548697, 6.779081503611968),
    (36.218051638900036, 6.7243445153570125),
    (32.400737418429216, 6.652125114457824),
    (28.735864839337697, 6.562708317895847),
    (25.237897479374148, 6.456447012916463),
    (21.92064021763908, 6.333760564344252),
    (18.79718475303387, 6.195133159541625),
    (15.879857937306236, 6.0411118975424944),
    (13.180173126598005, 5.872304629902357),
    (10.708784743488392, 5.689377561785878),
    (8.475446228855569, 5.493052622759485),
    (6.488971549501496, 5.284104617665191),
    (4.757200413451594, 5.063358168819828),
    (3.286967330208895, 4.8316844616075345),
    (2.084074638067364, 4.589997806309031),
    (1.1532696049334672, 4.339252029736645),
    (0.4982256930286379, 4.0804367109156665),
    (0.12152806141202838, 3.8145732756680006),
    (0.024663363538902687, 3.5427109655111297),
    (0.2080138801184492, 3.265922696781163),
    (0.6708560104266521, 2.9853008263222423),
    (1.4113631280275918, 2.701952840453139),
    (2.426612789633675, 2.416996984224689),
    (3.7125982686539536, 2.1315578482174877),
    (5.264244367913619, 1.846761930296613),
    (7.0754274491385845, 1.5637331898392164),
    (9.138999600158078, 1.2835886119803601),
    (11.4468168444485, 1.0074337993829612),
    (13.989771281687991, 0.7363586089292161),
    (16.75782703247815, 0.4714328505533679),
    (19.740059845375065, 0.21370206519065607),
    (22.92470020991869, -0.03581660149508132),
    (26.29917980551407, -0.27613841332067823),
    (29.85018110285037, -0.506314929887444),
    (33.563689922105276, -0.7254377496421445),
    (37.425050740509896, -0.9326420949228948),
    (41.419024531002, -1.127110224841536),
    (45.529848903703616, -1.3080746625333208),
    (49.7413003128726, -1.4748212240374596),
    (54.0367580838262, -1.6266918368549592),
    (58.39927000715034, -1.7630871370601089),
    (62.81161924132584, -1.8834688347160848),
    (67.25639225973609, -1.9873618382594065),
    (71.71604757390092, -2.074356129469285),
    (76.17298496171819, -2.144108381622228),
    (80.609614927499, -2.196343314445759),
    (85.00842811967199, -2.2308547805238947),
    (89.35206443219425, -2.247506578866816),
    (93.62338151695882, -2.2462329924339417),
    (97.80552243681143, -2.2270390474890807),
]

_BBB_POLYGON: list[tuple[float, float]] = [
    (40.97017925131679, 0.4062562899766126),
    (43.53440363567211, 0.4169942065264866),
    (46.077057183913354, 0.4386559712786629),
    (48.58810520411346, 0.4711560951439837),
    (51.05763773692548, 0.5143663149814472),
    (53.47590866566447, 0.5681160997942261),
    (55.83337417977759, 0.6321933237376053),
    (58.120730439904186, 0.7063451032827793),
    (60.328950295879224, 0.7902787952326094),
    (62.449318912770856, 0.8836631516506256),
    (64.47346816435247, 0.9861296271452998),
    (66.39340965827392, 1.0972738333503356),
    (68.20156626259653, 1.2166571348607977),
    (69.8908020092712, 1.3438083803266692),
    (71.45445025654422, 1.4782257618719723),
    (72.88633999914657, 1.61937879550121),
    (74.1808202224323, 1.766710414677333),
    (75.33278220435197, 1.9196391688088683),
    (76.33767967724427, 2.07756151796976),
    (77.19154676987765, 2.239854214795729),
    (77.89101365893231, 2.405876764156885),
    (78.43331986815312, 2.5749739508993854),
    (78.81632516268847, 2.7464784256803143),
    (79.03851799561927, 2.9197133386906526),
    (79.09902147334422, 3.093995010872254),
    (78.99759681627812, 3.2686356320867374),
    (78.73464430120595, 3.442945975587881),
    (78.31120168157305, 3.6162381180847065),
    (77.72894009194661, 3.7878281546604287),
    (76.99015745281086, 3.9570388978327133),
    (76.09776940172482, 4.1232025501032945),
    (75.05529778663279, 4.285663339449613),
    (73.86685676673952, 4.4437801073573935),
    (72.53713657580352, 4.596928839180382),
    (71.071385011927, 4.744505126841076),
    (69.47538672689447, 4.885926554153269),
    (67.75544039679461, 5.020634995352665),
    (65.91833386402362, 5.148098817764284),
    (63.97131734877222, 5.267814979913747),
    (61.92207483571886, 5.3793110168021645),
    (59.77869374885272, 5.482146904509627),
    (57.549633034105966, 5.575916796768607),
    (55.243689775758746, 5.660250626653745),
    (52.86996447836648, 5.734815567066945),
    (50.43782515122604, 5.799317344253877),
    (47.956870337122915, 5.853501399168046),
    (45.43689123126793, 5.897153892099043),
    (42.8878330399229, 5.930102546600198),
    (40.319755731215174, 5.952217329385),
    (37.74279433303931, 5.9634109635090855),
    (35.167118934732244, 5.963639272812449),
    (32.602894550376924, 5.952901356262576),
    (30.06024100213569, 5.931239591510399),
    (27.54919298193556, 5.898739467645077),
    (25.079660449123548, 5.855529247807613),
    (22.66138952038456, 5.801779462994835),
    (20.303924006271433, 5.7377022390514565),
    (18.016567746144844, 5.663550459506283),
    (15.808347890169804, 5.579616767556452),
    (13.687979273278186, 5.486232411138436),
    (11.663830021696565, 5.38376593564376),
    (9.743888527775118, 5.272621729438726),
    (7.935731923452518, 5.153238427928264),
    (6.2464961767778435, 5.026087182462394),
    (4.682847929504812, 4.8916698009170885),
    (3.2509581869024937, 4.750516767287851),
    (1.9564779636167104, 4.603185148111728),
    (0.8045159816970635, 4.450256393980193),
    (-0.20038149119524168, 4.2923340448193015),
    (-1.054248583828624, 4.130041347993332),
    (-1.7537154728832645, 3.9640187986321784),
    (-2.2960216821040977, 3.7949216118896762),
    (-2.67902697663943, 3.623417137108748),
    (-2.9012198095702453, 3.450182224098408),
    (-2.961723287295181, 3.275900551916808),
    (-2.8602986302290945, 3.1012599307023248),
    (-2.5973461151568977, 2.9269495872011797),
    (-2.173903495524005, 2.753657444704355),
    (-1.5916419058975677, 2.582067408128632),
    (-0.8528592667618298, 2.4128566649563483),
    (0.039528784324221584, 2.246693012685768),
    (1.0820003994162777, 2.0842322233394484),
    (2.2704414193095257, 1.9261154554316693),
    (3.6001616102455305, 1.7729667236086788),
    (5.0659131741220245, 1.6253904359479865),
    (6.6619114591545925, 1.4839690086357915),
    (8.381857789254436, 1.3492605674363958),
    (10.21896432202541, 1.2217967450247778),
    (12.165980837276834, 1.102080582875313),
    (14.215223350330179, 0.9905845459868972),
    (16.358604437196348, 0.8877486582794322),
    (18.58766515194309, 0.7939787660204534),
    (20.893608410290287, 0.7096449361353171),
    (23.26733370768257, 0.6350799957221163),
    (25.699473034822983, 0.5705782185351836),
    (28.18042784892613, 0.5163941636210154),
    (30.700406954781126, 0.4727416706900189),
    (33.24946514612614, 0.4397930161888647),
    (35.817542454833884, 0.41767823340406107),
    (38.39450385300971, 0.4064845992799761),
    (40.970179251316814, 0.4062562899766127),
]

# Golden triangle in plot space (LogP vs MW): vertices (LogP, MW).
_GOLDEN_TRIANGLE: list[tuple[float, float]] = [
    (-2.0, 200.0),
    (1.5, 450.0),
    (5.0, 200.0),
]

_MW_ALIASES = ("mw", "molwt", "mol wt", "molecular weight", "molecularweight", "exact mass")
_LOGP_ALIASES = ("logp", "clogp", "mollogp", "wlogp", "log p", "lipophilicity")
_TPSA_ALIASES = ("tpsa", "psa", "topological polar surface area", "topol polar surface area")
_WLOGP_ALIASES = ("wlogp", "wildman", "wildman-crippen")


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


_ALIAS_FAMILIES = (_MW_ALIASES, _LOGP_ALIASES, _TPSA_ALIASES, _WLOGP_ALIASES)


def resolve_descriptor_column(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    """Return the first header matching any alias (case/punctuation insensitive)."""
    norm_aliases = {_norm_header(a) for a in aliases}
    for family in _ALIAS_FAMILIES:
        fam_norm = {_norm_header(a) for a in family}
        if norm_aliases & fam_norm:
            norm_aliases |= fam_norm
    for h in headers:
        if _norm_header(h) in norm_aliases:
            return h
    return None


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting test for a closed polygon."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def descriptors_from_mol(mol: Chem.Mol) -> tuple[float, float, float, float]:
    """Return (TPSA, WLOGP, MW, LogP) using RDKit definitions aligned with BOILED-Egg."""
    tpsa = float(Descriptors.TPSA(mol, includeSandP=True))
    wlogp = float(Crippen.MolLogP(mol))
    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))
    return tpsa, wlogp, mw, logp


def classify_boiled_egg(tpsa: float, wlogp: float) -> tuple[bool, bool]:
    """Return (in_gia_egg_white, in_bbb_yolk)."""
    gia = _point_in_polygon(tpsa, wlogp, _GIA_POLYGON)
    bbb = _point_in_polygon(tpsa, wlogp, _BBB_POLYGON)
    return gia, bbb


def in_golden_triangle(logp: float, mw: float) -> bool:
    return _point_in_polygon(logp, mw, _GOLDEN_TRIANGLE)


def in_boiled_egg_regions(tpsa: float, logp: float) -> bool:
    """True when the compound lies in the GIA (egg white) or BBB (yolk) region."""
    gia, bbb = classify_boiled_egg(tpsa, logp)
    return gia or bbb


@dataclass(frozen=True)
class MedChemSpacePoint:
    oid: int
    tpsa: float
    wlogp: float
    mw: float
    logp: float
    hover: str
    gia: bool
    bbb: bool
    golden_triangle: bool


@dataclass(frozen=True)
class MedChemSpaceDataset:
    points: tuple[MedChemSpacePoint, ...]
    skipped: int
    subsample_note: str = ""
    gia_count: int | None = None
    bbb_count: int | None = None
    golden_triangle_count: int | None = None

    @property
    def oids(self) -> list[int]:
        return [p.oid for p in self.points]

    def subset_oids(self, keep: frozenset[int] | None) -> MedChemSpaceDataset:
        """Keep points whose OIDs are still visible in the table."""
        if keep is None:
            return self
        pts = tuple(p for p in self.points if int(p.oid) in keep)
        if len(pts) == len(self.points):
            return self
        return MedChemSpaceDataset(
            points=pts,
            skipped=self.skipped,
            subsample_note=self.subsample_note,
        )

    def summary_text(
        self, *, plot_kind: str = "boiled_egg", total_in_scope: int | None = None
    ) -> str:
        n = len(self.points)
        if n == 0:
            return "No compounds with valid descriptors in the current scope."
        total = total_in_scope if total_in_scope is not None else n
        lines = [f"{total:,} compound(s) in scope with valid descriptors."]
        if plot_kind == "golden_triangle":
            gt = self.golden_triangle_count
            if gt is None:
                gt = sum(1 for p in self.points if p.golden_triangle)
            lines.append(f"In golden triangle region: {gt:,}")
        else:
            gia = self.gia_count
            bbb = self.bbb_count
            if gia is None:
                gia = sum(1 for p in self.points if p.gia)
            if bbb is None:
                bbb = sum(1 for p in self.points if p.bbb)
            lines.append(f"GIA (intestinal absorption region): {gia:,}")
            lines.append(f"BBB (brain penetration yolk): {bbb:,}")
        if self.skipped:
            lines.append(f"Skipped {self.skipped:,} row(s) (missing structure or invalid values).")
        if self.subsample_note:
            lines.append(self.subsample_note)
        return "\n".join(lines)


@dataclass(frozen=True)
class MedChemRowSnapshot:
    """Lightweight row passed to the background worker (no Qt types)."""

    oid: int
    label: str
    structure_text: str
    tpsa_text: str
    wlogp_text: str
    mw_text: str
    logp_text: str


@dataclass(frozen=True)
class MedChemTableColumnPlan:
    """Resolved or default headers used when writing computed descriptors to the table."""

    tpsa: str
    logp: str
    mw: str
    wlogp: str


@dataclass(frozen=True)
class MedChemSpaceBuildResult:
    """Full-scope dataset plus the points sent to the interactive plot."""

    full: MedChemSpaceDataset
    plot: MedChemSpaceDataset
    table_updates: tuple[tuple[int, dict[str, str]], ...] = ()
    table_columns: tuple[str, ...] = ()


def medchem_table_column_plan(
    plot_kind: str,
    *,
    tpsa_col: str | None,
    logp_col: str | None,
    mw_col: str | None,
    wlogp_col: str | None,
) -> MedChemTableColumnPlan:
    """Headers to create or fill when descriptors are computed for the plot."""
    logp_h = logp_col or "LogP"
    wlogp_h = wlogp_col or logp_h
    if plot_kind == "golden_triangle":
        return MedChemTableColumnPlan(
            tpsa=tpsa_col or "TPSA",
            logp=logp_h,
            mw=mw_col or "MolWt",
            wlogp=wlogp_h,
        )
    return MedChemTableColumnPlan(
        tpsa=tpsa_col or "TPSA",
        logp=logp_h,
        mw=mw_col or "MolWt",
        wlogp=wlogp_h,
    )


def _format_descriptor_for_table(kind: str, value: float) -> str:
    if kind == "tpsa":
        return f"{value:.1f}"
    if kind == "mw":
        return f"{value:.2f}"
    return f"{value:.2f}"


def _collect_table_updates_for_snap(
    snap: MedChemRowSnapshot,
    plan: MedChemTableColumnPlan,
    *,
    tpsa: float,
    wlogp: float,
    mw: float,
    logp: float,
    plot_kind: str,
) -> dict[str, str]:
    """Values to write for cells that were empty before RDKit filled them."""
    out: dict[str, str] = {}
    if _parse_float_cell(snap.tpsa_text) is None:
        out[plan.tpsa] = _format_descriptor_for_table("tpsa", tpsa)
    if _parse_float_cell(snap.logp_text) is None:
        out[plan.logp] = _format_descriptor_for_table("logp", logp)
    if _parse_float_cell(snap.mw_text) is None:
        out[plan.mw] = _format_descriptor_for_table("mw", mw)
    if plan.wlogp != plan.logp and _parse_float_cell(snap.wlogp_text) is None:
        out[plan.wlogp] = _format_descriptor_for_table("logp", wlogp)
    elif plot_kind == "boiled_egg" and _parse_float_cell(snap.wlogp_text) is None:
        out[plan.wlogp] = _format_descriptor_for_table("logp", wlogp)
    return out


def required_descriptor_columns_ok(
    plot_kind: str,
    *,
    tpsa_col: str | None,
    logp_col: str | None,
    mw_col: str | None,
    wlogp_col: str | None = None,
) -> bool:
    """True when table columns cover descriptors for ``plot_kind`` (strict table-only mode)."""
    if plot_kind == "golden_triangle":
        return bool(mw_col and logp_col)
    return bool(tpsa_col and logp_col and mw_col and (wlogp_col or logp_col))


def snapshot_table_values_complete(
    plot_kind: str,
    *,
    tpsa: float | None,
    wlogp: float | None,
    mw: float | None,
    logp: float | None,
) -> bool:
    """True when this row already has every descriptor the plot reads from the table."""
    if plot_kind == "golden_triangle":
        return mw is not None and logp is not None
    return all(x is not None for x in (tpsa, wlogp, mw, logp))


def _mol_from_snapshot_structure(structure_text: str) -> Chem.Mol | None:
    raw = (structure_text or "").strip()
    if not raw:
        return None
    try:
        return parse_molecule_from_cell_text(raw)
    except Exception:
        return None


def _merge_descriptor_values(
    plot_kind: str,
    *,
    tpsa: float | None,
    wlogp: float | None,
    mw: float | None,
    logp: float | None,
    tpsa_m: float | None,
    wlogp_m: float | None,
    mw_m: float | None,
    logp_m: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Fill missing table values from RDKit; golden triangle only requires MW and LogP."""
    tpsa = tpsa if tpsa is not None else tpsa_m
    wlogp = wlogp if wlogp is not None else wlogp_m
    mw = mw if mw is not None else mw_m
    logp = logp if logp is not None else logp_m
    if plot_kind == "golden_triangle":
        if logp is None or mw is None:
            return None, None, None, None
        if tpsa is None:
            tpsa = 0.0
        if wlogp is None:
            wlogp = float(logp)
        return tpsa, wlogp, mw, logp
    if any(x is None for x in (tpsa, wlogp, mw, logp)):
        return None, None, None, None
    return tpsa, wlogp, mw, logp


def subsample_dataset(
    dataset: MedChemSpaceDataset,
    max_points: int | None = None,
    *,
    random_state: int = 42,
) -> MedChemSpaceDataset:
    """Return the full dataset, or a random subset when a point cap is set.

    ``max_points`` ``None`` uses :func:`medchem_plot_max_points`, which is also
    ``None`` unless ``MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS`` is set. Region counts
    stay on the full set either way.
    """
    cap = medchem_plot_max_points() if max_points is None else int(max_points)
    n = len(dataset.points)
    if cap is None or n <= cap:
        return dataset
    rng = np.random.default_rng(int(random_state))
    idx = np.sort(rng.choice(n, size=cap, replace=False))
    pts = tuple(dataset.points[int(i)] for i in idx)
    note = f"Plot shows {cap:,} of {n:,} compounds (random subsample, seed {random_state})."
    return MedChemSpaceDataset(points=pts, skipped=dataset.skipped, subsample_note=note)


def _point_from_values(
    *,
    oid: int,
    label: str,
    tpsa: float,
    wlogp: float,
    mw: float,
    logp: float,
) -> MedChemSpacePoint | None:
    if any(v != v for v in (tpsa, wlogp, mw, logp)):
        return None
    gia, bbb = classify_boiled_egg(tpsa, wlogp)
    gt = in_golden_triangle(logp, mw)
    hover = (
        f"{label}<br>"
        f"TPSA: {tpsa:.1f} Ų<br>"
        f"LogP: {wlogp:.2f}<br>"
        f"MW: {mw:.1f} Da<br>"
        f"GIA: {'yes' if gia else 'no'}; BBB: {'yes' if bbb else 'no'}; "
        f"Golden triangle: {'yes' if gt else 'no'}"
    )
    return MedChemSpacePoint(
        oid=int(oid),
        tpsa=tpsa,
        wlogp=wlogp,
        mw=mw,
        logp=logp,
        hover=hover,
        gia=gia,
        bbb=bbb,
        golden_triangle=gt,
    )


def build_medchem_space_from_snapshots(
    snapshots: list[MedChemRowSnapshot],
    *,
    plot_kind: str,
    tpsa_col: str | None,
    logp_col: str | None,
    mw_col: str | None,
    wlogp_col: str | None,
    use_table_columns_only: bool,
    oid_smiles: dict[int, str] | None = None,
    column_plan: MedChemTableColumnPlan | None = None,
    progress_state: object | None = None,
    progress_label: str = "Medchem plot",
    cancel_event: object | None = None,
) -> tuple[MedChemSpaceDataset, list[tuple[int, dict[str, str]]]]:
    """Build points from UI snapshots; fills gaps from structures when possible."""
    points: list[MedChemSpacePoint] = []
    table_updates: list[tuple[int, dict[str, str]]] = []
    skipped = 0
    gia_count = 0
    bbb_count = 0
    golden_triangle_count = 0
    plan = column_plan or medchem_table_column_plan(
        plot_kind,
        tpsa_col=tpsa_col,
        logp_col=logp_col,
        mw_col=mw_col,
        wlogp_col=wlogp_col,
    )
    smiles_by_oid = oid_smiles or {}
    total = len(snapshots)
    for idx, snap in enumerate(snapshots):
        if cancel_event is not None and cancel_event.is_set():
            raise MedChemSpaceCancelled()
        if progress_state is not None and (idx == 0 or idx % 200 == 0 or idx == total - 1):
            try:
                progress_state.update(progress_label, idx, total)
            except Exception:
                pass

        tpsa = _parse_float_cell(snap.tpsa_text) if tpsa_col else None
        wlogp = _parse_float_cell(snap.wlogp_text) if wlogp_col else None
        mw = _parse_float_cell(snap.mw_text) if mw_col else None
        logp = _parse_float_cell(snap.logp_text) if logp_col else None

        computed_from_mol = False
        if use_table_columns_only and snapshot_table_values_complete(
            plot_kind, tpsa=tpsa, wlogp=wlogp, mw=mw, logp=logp
        ):
            tpsa, wlogp, mw, logp = _merge_descriptor_values(
                plot_kind,
                tpsa=tpsa,
                wlogp=wlogp,
                mw=mw,
                logp=logp,
                tpsa_m=None,
                wlogp_m=None,
                mw_m=None,
                logp_m=None,
            )
        elif use_table_columns_only:
            structure_text = (snap.structure_text or "").strip()
            if not structure_text:
                structure_text = (smiles_by_oid.get(int(snap.oid)) or "").strip()
            tpsa_m = wlogp_m = mw_m = logp_m = None
            mol = _mol_from_snapshot_structure(structure_text)
            if mol is not None:
                try:
                    tpsa_m, wlogp_m, mw_m, logp_m = descriptors_from_mol(mol)
                    computed_from_mol = True
                except Exception:
                    tpsa_m = wlogp_m = mw_m = logp_m = None
            tpsa, wlogp, mw, logp = _merge_descriptor_values(
                plot_kind,
                tpsa=tpsa,
                wlogp=wlogp,
                mw=mw,
                logp=logp,
                tpsa_m=tpsa_m,
                wlogp_m=wlogp_m,
                mw_m=mw_m,
                logp_m=logp_m,
            )
            if tpsa is None:
                skipped += 1
                continue
        else:
            structure_text = (snap.structure_text or "").strip()
            if not structure_text:
                structure_text = (smiles_by_oid.get(int(snap.oid)) or "").strip()
            tpsa_m = wlogp_m = mw_m = logp_m = None
            mol = _mol_from_snapshot_structure(structure_text)
            if mol is not None:
                try:
                    tpsa_m, wlogp_m, mw_m, logp_m = descriptors_from_mol(mol)
                    computed_from_mol = True
                except Exception:
                    tpsa_m = wlogp_m = mw_m = logp_m = None
            if mol is None:
                skipped += 1
                continue
            tpsa, wlogp, mw, logp = _merge_descriptor_values(
                "boiled_egg",
                tpsa=tpsa,
                wlogp=wlogp,
                mw=mw,
                logp=logp,
                tpsa_m=tpsa_m,
                wlogp_m=wlogp_m,
                mw_m=mw_m,
                logp_m=logp_m,
            )
            if tpsa is None:
                skipped += 1
                continue

        pt = _point_from_values(
            oid=snap.oid,
            label=snap.label or f"OID {snap.oid}",
            tpsa=float(tpsa),
            wlogp=float(wlogp),
            mw=float(mw),
            logp=float(logp),
        )
        if pt is None:
            skipped += 1
            continue
        points.append(pt)
        if pt.gia:
            gia_count += 1
        if pt.bbb:
            bbb_count += 1
        if pt.golden_triangle:
            golden_triangle_count += 1
        if computed_from_mol:
            row_updates = _collect_table_updates_for_snap(
                snap,
                plan,
                tpsa=float(tpsa),
                wlogp=float(wlogp),
                mw=float(mw),
                logp=float(logp),
                plot_kind=plot_kind,
            )
            if row_updates:
                table_updates.append((int(snap.oid), row_updates))
    if progress_state is not None:
        try:
            progress_state.update(progress_label, total, total)
        except Exception:
            pass
    return MedChemSpaceDataset(
        points=tuple(points),
        skipped=skipped,
        gia_count=gia_count,
        bbb_count=bbb_count,
        golden_triangle_count=golden_triangle_count,
    ), table_updates


def build_medchem_space_result(
    snapshots: list[MedChemRowSnapshot],
    *,
    plot_kind: str,
    tpsa_col: str | None,
    logp_col: str | None,
    mw_col: str | None,
    wlogp_col: str | None,
    use_table_columns_only: bool,
    max_plot_points: int | None = None,
    oid_smiles: dict[int, str] | None = None,
    progress_state: object | None = None,
    progress_label: str = "Medchem plot",
    cancel_event: object | None = None,
) -> MedChemSpaceBuildResult:
    plan = medchem_table_column_plan(
        plot_kind,
        tpsa_col=tpsa_col,
        logp_col=logp_col,
        mw_col=mw_col,
        wlogp_col=wlogp_col,
    )
    full, table_updates = build_medchem_space_from_snapshots(
        snapshots,
        plot_kind=plot_kind,
        tpsa_col=tpsa_col,
        logp_col=logp_col,
        mw_col=mw_col,
        wlogp_col=wlogp_col,
        use_table_columns_only=use_table_columns_only,
        oid_smiles=oid_smiles,
        column_plan=plan,
        progress_state=progress_state,
        progress_label=progress_label,
        cancel_event=cancel_event,
    )
    plot = subsample_dataset(full, max_plot_points)
    cols = tuple(dict.fromkeys((plan.tpsa, plan.logp, plan.mw, plan.wlogp)))
    return MedChemSpaceBuildResult(
        full=full,
        plot=plot,
        table_updates=tuple(table_updates),
        table_columns=cols,
    )


def oids_in_egg_gia(dataset: MedChemSpaceDataset) -> list[int]:
    """Compounds in the BOILED-Egg GIA (egg white / whole-egg) region."""
    return [p.oid for p in dataset.points if p.gia]


def oids_in_egg_yolk(dataset: MedChemSpaceDataset) -> list[int]:
    """Compounds in the BOILED-Egg BBB (yolk) region."""
    return [p.oid for p in dataset.points if p.bbb]


def oids_in_golden_triangle_region(dataset: MedChemSpaceDataset) -> list[int]:
    return [p.oid for p in dataset.points if p.golden_triangle]


def _parse_float_cell(text: str) -> float | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def build_medchem_space_dataset(
    *,
    mol_rows: list[tuple[int, Chem.Mol]],
    row_values: dict[int, dict[str, str]] | None = None,
    mw_col: str | None = None,
    logp_col: str | None = None,
    tpsa_col: str | None = None,
    wlogp_col: str | None = None,
    id_labels: dict[int, str] | None = None,
) -> MedChemSpaceDataset:
    """
    Build plot points from structures, optionally overriding descriptors from table columns.

    ``row_values`` maps OID → {column header: cell text} for numeric overrides.
    """
    points: list[MedChemSpacePoint] = []
    skipped = 0
    for oid, mol in mol_rows:
        try:
            tpsa_m, wlogp_m, mw_m, logp_m = descriptors_from_mol(mol)
        except Exception:
            skipped += 1
            continue
        rv = (row_values or {}).get(int(oid), {})
        tpsa = _parse_float_cell(rv.get(tpsa_col, "")) if tpsa_col else None
        wlogp = _parse_float_cell(rv.get(wlogp_col, "")) if wlogp_col else None
        mw = _parse_float_cell(rv.get(mw_col, "")) if mw_col else None
        logp = _parse_float_cell(rv.get(logp_col, "")) if logp_col else None
        tpsa = tpsa if tpsa is not None else tpsa_m
        wlogp = wlogp if wlogp is not None else wlogp_m
        mw = mw if mw is not None else mw_m
        logp = logp if logp is not None else logp_m
        if any(v != v for v in (tpsa, wlogp, mw, logp)):  # NaN
            skipped += 1
            continue
        pt = _point_from_values(
            oid=int(oid),
            label=(id_labels or {}).get(int(oid), "") or f"OID {oid}",
            tpsa=tpsa,
            wlogp=wlogp,
            mw=mw,
            logp=logp,
        )
        if pt is None:
            skipped += 1
            continue
        points.append(pt)
    return MedChemSpaceDataset(points=tuple(points), skipped=skipped)


def gia_polygon() -> list[tuple[float, float]]:
    return list(_GIA_POLYGON)


def bbb_polygon() -> list[tuple[float, float]]:
    return list(_BBB_POLYGON)


def golden_triangle_polygon() -> list[tuple[float, float]]:
    return list(_GOLDEN_TRIANGLE)
