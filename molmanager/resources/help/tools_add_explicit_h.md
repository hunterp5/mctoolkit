# Add Explicit Hydrogens

Add Explicit Hydrogens expands implicit hydrogens on molecules using RDKit AddHs, updating the structure column accordingly.

## Goal

Materialize hydrogens when a downstream step expects explicit H (certain 3D or display workflows).

## When to use

Use before tools that behave differently with explicit hydrogens, or when inspecting protonation-related edits.

## Inputs / scope

Valid molecules in scope; optional **Selected Rows Only**.

## Options

- Structure source.
- **Selected Rows Only** when available.
- Run / apply to call RDKit **AddHs** on each molecule.

## Workflow

1. Select target rows if needed.
2. Run **Chemistry → Structure Preparation → Preparation Menu** and check **Add explicit hydrogens**.
3. Confirm depictions/H counts.
4. Continue to conformers or other prep.

## Use cases

- Prepare structures before some 3D minimization setups.
- Make hydrogen presence obvious for teaching/review.
- Pair with Remove Explicit Hydrogens to round-trip representations.

## Tips and limits

Explicit H increases atom counts and can slow fingerprints/depicts. Most 2D table work is fine with implicit H. Combining with protonation tools - apply in a deliberate order.
