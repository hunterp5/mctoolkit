# Generate Conformations (Stochastic)

Conformations → **Generate → Stochastic** builds 3D conformer ensembles per molecule with RDKit ETKDG, energy window, force field, and pruning controls, optionally writing to the table or SDF. When generation finishes, a 3D results window opens with per-conformer **E**, **ΔE vs ref**, **ΔE vs min**, **Pop. %**, and **RMSD**.

For a systematic torsion search instead of stochastic ETKDG, use **Conformations → Generate → Systematic…** (Open Babel Confab). For CONFORGE (CDPKit), use **CONFORGE…**.

## Goal

Sample low-energy 3D shapes for inspection, strain-aware review, or export to external modeling tools.

## When to use

Use when you need multiple conformers (not just one pose), especially for flexible ligands or ensemble exports.

## Inputs / scope

Scoped rows with valid structures; **Selected Rows Only** when checked. Output may go to table and/or SDF file.

## Options

- **Conformers** - ETKDG search budget (up to 1,000). This is how many poses to embed, not how many are stored.
- **Energy window** - keep conformers within this window (0 = keep all).
- **Force field** - MMFF94s (default), MMFF94, or UFF (MMFF variants fall back to UFF if parameters are missing). **GAFF2** / **GAFF** minimize each pose with AmberTools (antechamber / parmchk2 / tleap) and OpenMM in vacuum. Install steps are in **External tools**. They require AmberTools on PATH (WSL on Windows: Settings → Configure → WSL, or Settings → Configure → AmberTools) and OpenMM (`pip install 'openmm>=8.2,<8.3'`). There is no silent fallback to MMFF/UFF if parameterization fails.
- **Seed** - reproducibility control.
- **RMS prune (embed)** - drop near-duplicates during ETKDG embedding (−1 = ETKDG default).
- **RMS prune (post-min)** - after minimization, drop higher-energy poses within this RMS of a kept conformer (0 = off).
- **Max keep** - store at most this many lowest-energy survivors (default 100; 0 = no extra cap). Coordinates are stored on disk; table cells keep metadata only.
- **Max iterations** - minimizer budget.
- **Max embed attempts** - ETKDG embedding attempts per conformer (0 = RDKit default).
- **Align on** - optional SMILES (or SMARTS) substructure used to overlay the ensemble after generation. Leave empty to keep embedder orientations.
- **Options** - ETKDG flags (chirality, random coords, torsion preferences, small-ring / macrocycle torsions, basic knowledge, heavy-atom RMS), **Keep explicit hydrogens**, **Selected Rows Only**, and **Add as Entries**.
- **Save to SDF** - path and **Browse...** on one line below Options.

## Workflow

1. Select molecules and set the search budget (**Conformers**), energy window, and **Max keep**.
2. Choose force field, seed, RMS pruning, and optional **Align on** substructure.
3. Set ETKDG flags and hydrogen handling under **Options** when you need them.
4. Run generation (watch **Processes**).
5. Inspect the 3D results window: use **← →** to step through poses in table order (each step selects that row); click a row to select it and show that pose; check **Superpose** to overlay the ensemble, or **Selected Conformers** to overlay the table selection with a color legend. **View Conformers** on a packed cell reopens the same energy table. If several rows were processed, the window is the first ensemble; open the others from the table.
6. Optional: add results to the table and/or save SDF.

## Use cases

- Build ensembles for flexible linkers before manual review.
- Export multi-conformer SDF to an external docking suite.
- Compare conformer counts across a congeneric series.
- Tighten coverage with post-min RMS prune and **Max keep** after a wide energy window.

## Tips and limits

Cost scales with atoms × requested conformers × rows. GAFF/GAFF2 also run AM1-BCC (or Gasteiger) once per molecule, so they are slower than MMFF/UFF. A larger search budget with **Max keep** around 50–200 is usually better than storing every embedded pose. Force-field minima are not protein-aware. Failed embeddings skip or partially fill - check logs/status. Energies in the results window are vacuum molecular-mechanics totals (kcal/mol), not protein-bound or quantum-chemical values. The force field is the one chosen in this dialog (MMFF, MMFF94s, UFF, GAFF2, or GAFF). Optional **Align on** overlays the ensemble on a common substructure; flexible tails may still diverge after core overlay. Embed RMS prune happens before minimization; use **RMS prune (post-min)** to collapse poses that relaxed onto the same basin. Packed **confs** cells store metadata in the table; coordinates live in a disk-backed ensemble store (saved with the session). If a **confs** column already exists, new ensembles go to **confs (1)** (then **confs (2)**, …) so the previous column is kept.
