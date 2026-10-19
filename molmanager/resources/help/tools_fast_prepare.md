# Fast Prepare

Fast Prepare runs a practical cleanup pipeline (largest fragment, optional neutralize, redraw) as one background job on scoped rows.

## Goal

Get to standardized parent-like structures suitable for descriptors and modeling without stepping through each cleanup tool manually.

## When to use

Use on freshly imported vendor files, salts/solvates, or messy SMILES before serious analysis.

## Inputs / scope

Structure column rows in scope (all or **Selected Rows Only** when offered).

## Options

- Structure source / target as presented in the tool.
- **Neutralize** - off by default; when checked, RDKit Uncharger zeros net formal charge on the largest fragment (same method as Chemistry → Prepare Structures → Protonate → Neutralize).
- **Selected Rows Only** when available.
- Combined cleanup actions: keep largest fragment, redraw 2D.
- Run control to start the background job.

## Workflow

1. Select messy rows or leave scope as the full table.
2. Launch **Fast Prepare** and confirm the structure source.
3. Check **Neutralize** if you want Uncharger applied after keeping the largest fragment.
4. Wait for the job to finish.
5. Spot-check depictions and formal charges.

## Use cases

- Clean a purchasing SDF before descriptor calculation.
- Normalize salt-containing rows prior to clustering.
- Redraw awkward coordinates after SMILES import.

## Tips and limits

Largest-fragment logic can drop meaningful counter-ions or linked partners - review edge cases. Neutralization is heuristic. Keep a session duplicate if you need the original forms.
