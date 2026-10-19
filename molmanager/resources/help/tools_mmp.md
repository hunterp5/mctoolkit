# MMP Transform Ledger

Matched Molecular Pair (MMP) analysis finds pairs related by small transformations, with controls for cuts, variable heavy atoms, and optional activity differences. Open from **Data → MMP**. After a run, right-click an **MMP_Partners**, **MMP_Transforms**, or **MMP_Delta_*** column and choose **Transform Ledger** to reopen the ledger for that analysis.

## Goal

Learn how small structural changes correlate with property/activity shifts in your table, then rank those changes as reusable transform rules.

## When to use

Use on cleaned series with a meaningful activity column when you want transformation rules rather than global models.

## Inputs / scope

Structures from **Molecules from**; optional **Activity column**. Scope via **Selected Rows Only**.

## Options

**Activity**

- **Molecules from** - structure source.
- **Activity column** - property for deltas.
- **Minimum activity difference** - filter weak deltas (0 = no floor).
- **Maximum activity difference** - exclude large deltas (0 = no ceiling).
- **Selected Rows Only**.

**Core**

- **Core / MCS** - optional SMARTS or SMILES constant core; use **MCS from selection** to fill from selected molecules. When set, only matching molecules are analyzed and only fragmentations whose constant core still contains the pattern are kept.

**Fragmentation**

- **Max cuts** - fragmentation aggressiveness.
- **Max variable heavy atoms** - size of the changing fragment.
- **OK** / **Cancel**.

## Workflow

1. Select or filter to a relevant chemical space.
2. Set cuts, variable-atom cap, and activity column.
3. Run MMP. Annotation columns (**MMP_Partners**, **MMP_Transforms**, **MMP_Delta_…**) are written to the table, and results open in the **transform ledger**, which groups pairs by chemically canonical `from>>to` fragment swap.
4. Sort or filter the ledger by support (**n**), median/mean Δ, or win rate.
5. Select a transform row; **Browse Pairs** (far left) opens the pair stepper for that rule's evidence.
6. Optionally click **Make Reference** (far right) with exactly one table molecule selected to show only pairs involving that compound; transforms and Δ are then oriented as reference → partner. Click again without a single-row selection to show all pairs.
7. **Activity Cliffs** opens a scatter of structural-change size vs |Δactivity| for the pairs currently shown (respects reference filter).
8. **Pair Network** opens the neighborhood graph for the pairs currently shown (respects reference filter).
9. After **Save Session**, reopen via right-click on an MMP annotation column (**MMP_Partners**, **MMP_Transforms**, or **MMP_Delta_…**) → **Transform Ledger**.

## Use cases

- Find potency-increasing halogen swaps with enough supporting pairs.
- Mine solubility cliffs between matched pairs.
- Restrict to selected series to avoid cross-chemotype noise.

## Tips and limits

MMP depends on fragmentation parameters - too-loose cuts explode pairs. Activity noise produces spurious cliffs; set a minimum and/or maximum difference. Ledger transforms are oriented with lexicographically ordered sidechains so the same chemical swap shares one row (Δ is flipped when sides are swapped). Not a substitute for full QSAR on diverse libraries.
