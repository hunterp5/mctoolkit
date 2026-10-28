# Generate Conformations (CONFORGE)

Conformations → **Generate → CONFORGE** builds 3D conformer ensembles with **CONFORGE** from CDPKit: knowledge-based fragment and torsion libraries for typical drug-like molecules, and stochastic distance geometry for large macrocycles. When generation finishes, a 3D results window opens with per-conformer **E**, **ΔE vs ref**, **ΔE vs min**, **Pop. %**, and **RMSD**.

For RDKit ETKDG, use **Conformations → Generate → Stochastic…**. For Open Babel Confab, use **Systematic…**.

## Goal

Generate high-quality vacuum ensembles from connectivity (no input 3D required) for inspection, strain review, or export.

## When to use

Use when you want CONFORGE’s published knowledge-based sampling instead of RDKit ETKDG or Confab, including salts/mixtures and many macrocycles.

## Inputs / scope

Scoped rows with valid structures; **Selected Rows Only** when checked. Output may go to table and/or SDF file. CONFORGE is optional. Install and path setup are in **External tools**.

**Windows (Python 3.11):** PyPI has no `cdpkit` wheel, so `pip install cdpkit` compiles from source and fails without Boost. Install the CDPKit **MSVC** installer from [GitHub Releases](https://github.com/molinfo-vienna/CDPKit/releases), then set `confgen.exe` under **Settings → Configure → CONFORGE** (usually `C:\Program Files\CDPKit\Bin\confgen.exe`) or add that `Bin` folder to PATH.

**Linux/macOS:** `pip install cdpkit` (or `pip install -e ".[conforge]"`) when a wheel exists. You can also place `confgen` on PATH or under `resources/bin`.

CONFORGE generates from the connection table. 3D input is only needed if you check **Include input conformation**.

## Options

- **Max conformers** - output cap per molecule (`-n`, default 100; 0 = no cap).
- **Energy window** - keep poses within this window of the lowest CONFORGE energy (`-e`, default 15 kcal/mol).
- **RMSD cutoff** - minimum RMSD between kept poses (`-r`, default 0.5 Å; 0 = off).
- **Preset** - SMALL/MEDIUM/LARGE × diverse or dense (`-C`, default Medium diverse). Energy, RMSD, and max conformers still apply after the preset.
- **Sampling** - Auto, Systematic, or Stochastic (`-m`, default Auto). Auto uses systematic sampling until a large macrocycle rotatable-bond threshold, then stochastic DG.
- **Timeout** - per-molecule limit (`-T`, default 3600 s; 0 = no limit).
- **Options** - **Include input conformation**, **Keep explicit hydrogens**, **Selected Rows Only**, and **Add as Entries**.
- **Save to SDF** - path and **Browse...** on one line below Options.

## Workflow

1. Install CDPKit (`confgen` on Windows; `pip install cdpkit` on Linux/macOS when a wheel exists), then select ligands in the table.
2. Set max conformers, energy/RMSD, and a preset.
3. Run generation (watch **Processes**). Flexible or macrocyclic molecules can take minutes per ligand.
4. Inspect the 3D results window. **View Conformers** on a packed cell reopens the same energy table.
5. Optional: add results to the table and/or save SDF.

## Use cases

- Knowledge-based ensembles for docking or strain review.
- Macrocycles that need CONFORGE’s stochastic DG path.
- Compare CONFORGE with Stochastic and Systematic on the same series.

## Tips and limits

Install is optional. On Windows 3.11 use the CDPKit installer + `confgen.exe`; `pip install cdpkit` has no matching wheel and will try to compile (needs Boost). Energies shown after the run are vacuum MMFF totals computed in MolManager, not protein-bound or quantum-chemical values. CONFORGE itself is not protein-aware. If a **confs** column already exists, new ensembles go to **confs (1)** (then **confs (2)**, …) so the previous column is kept.
