# Screen Pharmacophore

Find table molecules whose packed conformers match a 3D pharmacophore saved from a crystal ligand.

## Goal

Given a pharmacophore (donors, acceptors, aromatic centroids, …) from Protein Viewer, score every row’s conformation ensemble and write match / score / RMSD / best-conformer columns. Hits are molecules that can place the same feature **types** (and **atom** when set) with a compatible **distance distribution** — they do not need to share the protein coordinate frame.

## When to use

Use after you have:

1. A pharmacophore JSON from **Protein Viewer → Tools → Pharmacophore → Editor** (**From ligand** or placed sites, then **Save…**).
2. Packed 3D ensembles on the table (**Chemistry → Conformations → Generate**, or `superpose` / `poses`).

This is not Gobbi 2D pharmacophore fingerprints (those ignore ensembles and the crystal JSON). **Exclusion** volumes are protein-frame and are skipped here.

## Inputs / scope

- **Pharmacophore** — MolManager JSON (`.json` / `.mph4`). **Protein Viewer → Tools → Pharmacophore → Screen Table…** fills this from the live pharmacophore.
- **Ensembles** — packed `confs`, `superpose`, or `poses` column. Each conformer is scored; the best match is kept per row.
- **Distance slack** — allowed difference (Å) between query pairwise feature distances and ligand pairwise distances (default 1.2 Å).
- **Require all features** — every enabled non-Exclusion site must map onto a unique same-type RDKit BaseFeatures site (same element when **Atom** is set). Uncheck and set **Min** for a looser screen.
- **Only selected rows** — optional scope.
- **Select Hits in Table** — on by default; after the run, select every row that matched.
- **Column prefix** — writes `{prefix}Match`, `{prefix}Score`, `{prefix}RMSD`, `{prefix}Conf` (default `pharma`).

Non-hits stay in the table (`Match` = 0). Rows with no 3D ensemble are `N/A`. Filter on `pharmaMatch` to hide misses.

## Options

- **Screen** — start the run; the window closes. Work continues in the background. Cancel with the usual tool-progress Stop.
- Matching uses RDKit `BaseFeatures.fdef` families on each conformer, then Kabsch RMSD of the assigned feature centroids. A query **Atom** (C, N, O, …) must match the ligand site element; **Any** matches every element. Score is `1 / (1 + RMSD)`.

## Workflow

1. In Protein Viewer **Tools → Pharmacophore → Editor**, **From ligand** (or place sites) on the crystal ligand; **Save…** the pharmacophore.
2. Generate conformers for the compound table.
3. **Chemistry → Conformations → Screen Pharmacophore…** (or **Pharmacophore → Screen Table…**).
4. Sort or filter on `pharmaMatch` / `pharmaScore`. Inspect `pharmaConf` in the packed ensemble viewer.

## Use cases

- Analog search: keep table molecules that can reproduce the crystal ligand’s donor/acceptor/aromatic pattern.
- Pose ensembles: screen `poses` the same way (still distance-based, not pocket XYZ overlay).
