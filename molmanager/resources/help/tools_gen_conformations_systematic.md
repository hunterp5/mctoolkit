# Generate Conformations (Systematic)

Conformations → **Generate → Systematic** builds 3D conformer ensembles with Open Babel **Confab**, a knowledge-based systematic torsion search. When generation finishes, a 3D results window opens with per-conformer **E**, **ΔE vs ref**, **ΔE vs min**, **Pop. %**, and **RMSD**.

For RDKit ETKDG stochastic sampling, use **Conformations → Generate → Stochastic…**. For CONFORGE (CDPKit), use **CONFORGE…**.

## Goal

Enumerate diverse low-energy ligand shapes by driving rotatable bonds, then inspect or export the ensemble.

## When to use

Use for flexible ligands when you want a systematic (not stochastic) search, or when you already rely on Open Babel Confab in other workflows.

## Inputs / scope

Scoped rows with valid structures; **Selected Rows Only** when checked. Output may go to table and/or SDF file. Open Babel is installed with the project (`pip install openbabel`). The `obabel` path is **Settings → Configure → Open Babel**. A copy under `resources/bin` is used when that path is blank.

Confab requires a 3D starting geometry. If a row is 2D, MolManager embeds once with ETKDG before calling Confab.

## Options

- **Max conformers** - Confab `--conf` cap on how many poses to test (default 100). RMSD and energy cutoffs usually keep fewer.
- **RMSD cutoff** - diversity cutoff (`--rcutoff`, default 0.5 Å).
- **Energy cutoff** - keep poses within this window of the lowest Confab energy (`--ecutoff`, default 50 kcal/mol).
- **Options** - **Include input conformation**, **Keep explicit hydrogens**, **Selected Rows Only**, and **Add as Entries**.
- **Save to SDF** - path and **Browse...** on one line below Options.

## Workflow

1. Install Open Babel if needed, then select ligands in the table.
2. Set max conformers and RMSD / energy cutoffs.
3. Run generation (watch **Processes**). Flexible molecules can take minutes per ligand.
4. Inspect the 3D results window. **View Conformers** on a packed cell reopens the same energy table.
5. Optional: add results to the table and/or save SDF.

## Use cases

- Systematic coverage of rotatable bonds before docking or strain review.
- Compare Confab ensembles with Stochastic on the same series.
- Export multi-conformer SDF to an external modeling suite.

## Tips and limits

Confab cost grows quickly with rotatable bonds. The `--conf` value is a test budget, not a guarantee of that many unique poses. Energies shown after the run are vacuum MMFF/UFF totals computed in MolManager, not protein-bound or quantum-chemical values. Confab itself is not protein-aware. If a **confs** column already exists, new ensembles go to **confs (1)** (then **confs (2)**, …) so the previous column is kept.
