# Remove Explicit Hydrogens

Remove Explicit Hydrogens strips explicit hydrogens with RDKit RemoveHs, returning to a compact implicit-H representation.

## Goal

Simplify structures after hydrogen-aware steps so the table stays light and consistent for general cheminformatics.

## When to use

Use after Add Explicit Hydrogens, certain imports, or when depictions look cluttered with H atoms.

## Inputs / scope

Molecules in the chosen structure scope; optional **Selected Rows Only**.

## Options

- Structure source.
- **Selected Rows Only** when available.
- Run / apply to call RDKit **RemoveHs**.

## Workflow

1. Scope the rows that still carry explicit H.
2. Run **Chemistry → Structure Preparation → Preparation Menu** and check **Remove explicit hydrogens**.
3. Verify valence-correct depictions.
4. Proceed with descriptors or export.

## Use cases

- Clean structures after 3D work before sharing SDF.
- Standardize mixed implicit/explicit libraries.
- Reduce clutter prior to publication-quality 2D renders.

## Tips and limits

Removing H does not replace proper neutralization/protonation. Stereo/implicit-H edge cases are rare but worth spot-checking. Re-run Render 2D if coordinates look stale.
