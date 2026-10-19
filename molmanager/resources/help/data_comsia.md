# CoMSIA

CoMSIA fits a PLS model to Gaussian 3D fields of aligned poses and writes predicted activities back to the table.

## Goal

Explain activity differences that depend on shape, charge, hydrophobicity, or hydrogen bonding, using poses that already share one coordinate frame.

## When to use

Open it from **Data → QSAR → CoMSIA**. Use it on a congeneric series after **Chemistry → Conformations → Superpose**, or on docked poses in one receptor frame. Use **Generate Model** when the features are ordinary table columns or 2D fingerprints.

## Inputs / scope

Labeled rows with an **Activity (Y)** column and a packed pose column (`superpose`, `poses`, or `confs`). The model uses the first 3D conformer in each cell. Scope: **Selected Rows Only**, or every table row when that box is unchecked.

## Options

- **Activity (Y)** / **Poses** / **Refresh columns**.
- **Fields** — steric (van der Waals radius cubed), electrostatic (Gasteiger charge), hydrophobic (Crippen atomic logP), H-bond donor, and H-bond acceptor.
- **Spacing** and **Padding** — grid step and the margin around the training poses. The lattice is taken from the training poses only.
- **Max components** — largest PLS rank to test. The fit keeps the smallest count whose leave-one-out q² is within 0.05 of the best score.
- **Flat-point cutoff** — drop a grid point whose standard deviation is below this fraction of the field's standard deviation. The cutoff is refit inside each leave-one-out fold.
- **Prediction column**; **Train/Evaluate**; **Add predictions to table**.

## Workflow

1. Superpose the series on a common core, or dock the ligands into one receptor.
2. Choose the activity column and the pose column. Prefer `superpose` or `poses`.
3. Train and read q², SDEP, and the fitted R². Trust q² more than the fitted R².
4. Add predictions. Rows in scope that have a pose are scored, including rows with no activity.

## Use cases

- Rank analogs on a superposed scaffold when 2D descriptors barely change.
- Build a steric and electrostatic model from Gnina poses that already share the pocket frame.
- Compare donor and acceptor fields on a series with a conserved hydrogen-bond motif.

## Tips and limits

The poses must already be aligned. A `confs` column contributes only its first 3D conformer, which is often not the bound pose. Donor probes follow explicit hydrogens; a heavy-atom pose places one donor probe opposite the bonded neighbors. Acceptor probes follow lone-pair directions in the molecule, including two in-plane probes on a carbonyl. Small sets overfit: a high fitted R² with a weak q² is not a usable model. Coefficient contour maps are not drawn yet.
