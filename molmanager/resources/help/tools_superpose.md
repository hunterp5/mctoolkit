# Superpose

Superpose overlays molecules for visual comparison. One dialog covers both **conformers in each row** and **structures across rows**, with **3D spatial** or **2D topological** geometry. Results go to a new **superpose** column and open in the 3D results window (2D overlays appear as planar coordinates).

## Goal

Put related poses or analogs into a common frame so cores line up and differences stand out.

## When to use

Use **Conformers** after generating ensembles when you want a shared frame per molecule. Use **Structures** on a congeneric series (matched pairs, R-group variants) to overlay scaffolds. Pick **2D topological** when you care about drawing orientation (SAR tables); pick **3D spatial** for coordinate overlays and energies.

## Inputs / scope

- **Conformers:** packed multi-conformer **confs** cells; scope controls which rows are processed.
- **Structures:** at least two rows with usable coordinates; **Selected Rows Only** is recommended. Reference is the first row in table order. 3D spatial embeds a conformer when the structure is 2D-only. 2D topological can run from table structures without 3D.

## Options

- **Align** - conformers in each row, or structures across rows.
- **Geometry** - **3D spatial** (AlignMol / O3A) or **2D topological** (regenerate drawings constrained to a common core via GenerateDepictionMatching2DStructure).
- **Source** - Structure, **confs**, or **superpose** (structures only).
- **Reference index** - which conformer is the frame (conformers only).
- **Align on** - whole molecule; **largest ring system** (fused SSSR set with the most atoms); **most central ring** (SSSR ring nearest the molecule centroid, or graph center when there are no 3D coordinates); or a custom SMILES/SMARTS pattern.
- **Pattern** / **SMARTS** - shown when Align on is custom. For structures, a miss falls through to MCS or O3A. For conformers the pattern must match.
- **Max iterations** - 3D AlignMol iterations.
- **Heavy atoms only** - ignore hydrogens in the atom map.
- **Allow reflection** - 3D AlignMol option.
- **Use MCS when no atom map** - maximum common substructure (structures).
- **O3A overlay if no atom map** - 3D fallback when pattern, ring, and MCS fail (structures).
- **Selected Rows Only** - scope.

## Workflow

1. Select the series (or generate **confs** first for per-row ensembles).
2. Open **Chemistry → Conformations → Superpose…**. Choose what to align, the geometry, and what to overlay on (whole molecule, a ring, or a custom core).
3. Optionally set a SMARTS core; leave MCS on for analog series.
4. Run. Inspect the results window (overlay plus energy table when 3D topologies match). Browser arrows step through poses. If several conformer rows were processed, the first overlay opens; use **View Conformers** on other **superpose** cells.

## Use cases

- Compare ring-flip conformers of one ligand (3D spatial, conformers).
- Overlay a matched-pair series on a hinge core (3D spatial, structures).
- Align 2D drawings of analogs so the scaffold sits in the same orientation (2D topological, structures).
- Superpose fused-ring analogs on the largest ring system, or a pendant aryl series on the most central ring.
- QA geometry before exporting a 3D SDF set.

## Tips and limits

MCS can be slow or ambiguous on distant analogs. Poor SMARTS yields wrong overlays - test on two rows first. Ring modes need a ring on the reference; acyclic molecules fail with no ring for alignment. 2D topological of identical graphs (conformers without a core pattern) produces a shared 2D layout. This does not dock to a protein. If a **superpose** column already exists, new overlays go to **superpose (1)** (then **superpose (2)**, …) so the previous column is kept.
