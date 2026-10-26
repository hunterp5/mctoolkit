# Calculate Descriptors

Calculate Descriptors computes RDKit and related property columns (physicochemical, names, drug-likeness, counts, fingerprints, and more) into the table.

## Goal

Add numeric/text descriptor columns used by filters, plots, MPO, and models.

## When to use

Use after loading structures and before property-based triage, MPO scoring, or feature selection for QSAR.

## Inputs / scope

Rows with valid molecules in the chosen **Target Column** / structure source. Optional **Selected Rows Only** limits computation.

## Options

- **Target Column** - structure column to describe.
- **Selected Rows Only** - compute for the selection when checked.
- Category tabs / groups such as **Physiochemical**, **3D**, **Name**, **Drug-likeness**, **Structural Alerts**, **Structural Counts**, **Ring Counts**, **Atom Counts**, **Complexity**, **Electronic**, **Fingerprints**.
- Per-descriptor checkboxes (e.g. LogP, Mol Weight, TPSA, QED, rule-of-five style flags). Hover a checkbox for a short description.
- **Structural Alerts** lists RDKit FilterCatalog sets (PAINS, Brenk, NIH, ZINC, and ChEMBL sets when this RDKit includes them). Each checked catalog writes a count column and a column of matched pattern names. No hit is `0` and a blank name cell. Invalid structures write **N/A**. These are the catalogs compiled into RDKit, not the Lilly medchem rules.
- **Name** writes local identifiers: SMILES, InChI Key, and molecular formula.
- Confirm with **OK** to run (often as a background job).
- **QED Score**, **AB-MPS score**, and **CNS MPO score** columns are colored automatically (green = more favorable, through yellow, to red). QED uses 0–1, CNS MPO 0–6, and AB-MPS 0–14 (literature threshold) with worse values trending red. Change or clear this with the column header **Color** action.

## Workflow

1. Choose the structure **Target Column** and scope.
2. Open the category tabs and tick the descriptors you need.
3. Run the calculation and wait for **Processes** to finish.
4. Use new columns in filters, plots, or MPO/QSAR.

## Use cases

- Compute MW/LogP/TPSA for BOILED-Egg, Golden Triangle, or the LipE plot (LogP).
- Add drug-likeness flags before slider filtering.
- Flag PAINS, Brenk, or NIH patterns and filter on the count column.
- Generate fingerprint bit columns when a workflow expects them in-table.

## Tips and limits

LogD 7.4, LogS 7.4, CNS MPO, and AB-MPS use a Uni-pKa ionization ensemble when the pka extra is installed; otherwise they fall back to heuristics. Those jobs also write a shared **pKa** column (updated in place). For **pI**, use Predict pKa with **Calculate isoelectric point**. Re-running any other descriptor that already exists writes a new column (`Name (1)`, …) and leaves the original. Re-running ionization-dependent scores after switching from pkasolver is a new method, not a refresh. QED / AB-MPS / CNS MPO coloring uses fixed score ranges, not min/max of the current table.

The **3D** tab (PMI, NPR, asphericity, PBF, SASA, volume, …) needs 3D coordinates. The Structure column is a 2D depiction, so these descriptors read packed **confs** (or **superpose**) from Generate Conformers or a 3D import. Rows without 3D write **N/A**. Values use the lowest-energy conformer in the packed ensemble (MMFF94 single-point, UFF fallback; lowest conformer id on ties). **Labute ASA** on the Physiochemical tab is the 2D Labute approximation, not 3D SASA.

**HOMO (eV)**, **LUMO (eV)**, and **HOMO-LUMO gap (eV)** on the Electronic tab are a GFN2-xTB single point. When **confs** or **superpose** has 3D coordinates, the single point uses that lowest-energy conformer. A 2D structure with no packed conformer is embedded once (ETKDG) and minimized with MMFF94 (UFF fallback); that pose is not written back to the table. An `xtb` install (Settings → Configure → xtb) or the `tblite` package is required. Rows that cannot be embedded, are not a closed-shell singlet, or have no engine write **N/A**. These are gas-phase tight-binding orbital energies on the MMFF pose, not a DFT reoptimization. Partial charges on the same tab stay Gasteiger.
