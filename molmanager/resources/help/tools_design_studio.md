# Drug Design Studio

The Drug Design Studio is a sketcher with a live property strip. Descriptors and a druglike MPO score update as the sketch changes. An empty SAR Matrix cell can be built into that sketch.

## Goal

Edit one analog and see molecular weight, lipophilicity, polarity, QED, and a combined desirability score without leaving the table.

## When to use

Use **Tools → Drug Design Studio** to draw or edit a structure in its own window. Use it from **Data → SAR Matrix** when a cell is a combination you have not made and you want that structure on the canvas.

## Inputs / scope

The strip reads the molecule on the canvas. SAR Matrix can send a row's structure, or build one from a Core column plus the R-group labels on the axes. Those labels are the SMILES from **Chemistry → Structure Decomposition → Core-Based Decomposition** (`[*:1]`, `[H][*:2]`, and so on). The rows in the matrix need to share one core SMILES.

## Options

- **Canvas** — the sketcher. Drawing, templates, and **File → Export to Table** work as they do in the standalone sketcher.
- **Add to table** — append the current sketch as a new row.
- **Dock beside the table** — the footer button moves the studio into the workspace. **Open in a separate window** sends a docked studio back out.
- **Druglike MPO** — geometric mean of five desirabilities:
  - **MW** is 1 at or below 350 and 0 at or above 500.
  - **LogP** is 1 at 2.5 and 0 outside 0–5.
  - **TPSA** is 1 at 75 and 0 outside 20–140.
  - **QED** is 0 at or below 0.3 and 1 at or above 0.7.
  - **Rotatable bonds** are 1 at or below 5 and 0 at or above 10.
- **LogD, pKa, CNS MPO, AB-MPS** — a fast estimate appears first. Uni-pKa replaces LogD, CNS MPO, and AB-MPS when it finishes, and fills pKa.
- **Design** on the SAR Matrix — open the selected cell. A filled cell loads that row. An empty or predicted cell builds the analog.

## Workflow

1. Open **Tools → Drug Design Studio**, or right-click a structure cell and choose **Open in Design Studio**. It opens in its own window. The table row stays unchanged.
2. Draw or edit. The strip refreshes shortly after each change.
3. **Add to table** when the analog is one you want to keep.
4. From a SAR Matrix, click an empty or predicted cell. **Design** sends the selected cell, including one that already has a compound.

## Use cases

- Check MW, LogP, TPSA, and QED while drawing a single change.
- Turn a missing R1 × R2 cell into a structure you can edit and then add to the table.
- Open a made analog from the grid and adjust it without hunting the row in the sketcher menu.

## Tips and limits

The druglike score is a fixed profile, not the criteria from **Data → MPO Scoring**. A property outside its gate makes the geometric mean zero. Building a cell needs one shared Core SMILES and R-group labels that each contain an attachment point. A series with two different cores, or labels that are names rather than SMILES, stays on the status line and does not change the sketch. pKa stays blank when Uni-pKa cannot assign a value; the other scores keep the fast estimate. If the studio is already docked, opening it again shows that pane instead of a second window.
