# Hansch analysis

Hansch analysis fits biological activity of a congeneric series to hydrophobic, electronic, and steric substituent constants on a shared core.

## Goal

Read the Hansch equation for the series: how activity depends on π, σ (or F and R), and an optional steric constant at each attachment point.

## When to use

Use **Data → Hansch…** when the compounds share one core and you have a constants file for the substituents. Use **Free-Wilson** when you want an additive contribution for each substituent instead of a physicochemical constant. Use **QSAR** when the series does not share one core.

## Inputs / scope

Molecules from the chosen structure source, a numeric activity column, a core SMARTS or SMILES, and a local CSV of substituent constants. Optional **Selected Rows Only**.

## Options

**Core**

- **Core (SMARTS or SMILES)** — label each attachment point with a dummy (`[*:1]`, `[*:2]`, …).
- **Matching strategy** — Greedy or Exhaustive.
- **Only match at R-groups**.

**Constants file**

A CSV you keep. MolManager does not ship the published constant tables. The header is:

`smiles,pi,sigma_m,sigma_p,f,r,es,mr,upsilon,sigma_star`

`smiles` is `H` for hydrogen and an attachment SMILES such as `*C` or `*Cl` for other groups. A blank cell means that constant is unknown. Es is used exactly as stored: do not mix a methyl-zero scale with a hydrogen-zero scale in one column.

**Terms**

- **π** and optional **π²**, one column per position.
- **Hammett σ**, with a default of meta or para and optional overrides such as `R1=meta, R2=para`. **Field and resonance** uses F and R instead of choosing meta or para.
- One steric term: **Es**, **molar refractivity**, or **υ**.

## Workflow

1. Filter to the series, enter the core, and choose the constants file.
2. Choose the terms. Run.
3. Read the equation, standard errors, t, p, r², q², and VIF.
4. **Write predictions** to add `Hansch_Predicted` on fitted rows.

Nothing is written until you use that button.

## Tips and limits

A substituent that is not in the file, or that is missing a selected constant, drops that molecule from the fit and is listed. A column that does not vary, or that duplicates another column, is marked not identifiable. Log the activity column first when the series needs a log scale. q² is leave-one-out and is blank when the fit is saturated.
