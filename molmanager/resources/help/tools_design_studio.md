# Design Studio

The Design Studio is a sketcher with a live property strip and a design list. Descriptors and a druglike MPO score update as the sketch changes. The status bar along the bottom reports the same sketch messages as the sketcher. An empty SAR Matrix cell can be built into that sketch.

## Goal

Edit one analog and see molecular weight, lipophilicity, polarity, QED, and a combined desirability score without leaving the table.

## When to use

Use **Tools → Design Studio** to draw or edit a structure in its own window. Use it from **Data → SAR Matrix**, or right-click a structure and choose **Open in Design Studio**, when you want that structure on the canvas. The window is not docked into the table.

## Inputs / scope

The strip reads the molecule on the canvas. SAR Matrix can send a row's structure, or build one from a Core column plus the R-group labels on the axes. Those labels are the SMILES from **Chemistry → Structure Decomposition → Core-Based** (`[*:1]`, `[H][*:2]`, and so on). The rows in the matrix need to share one core SMILES.

## Options

- **Canvas** — the sketcher. **Edit → Clear Sketch** empties the drawing. **View → Fit structure to window** scales it to the canvas, and **Original size** restores the size it had when it was opened. Ring templates show the heavy atoms they place. **File → Add to Table** asks, then adds new rows, as in the standalone sketcher.
- **Chemistry → Bioisosteric Replacement** — select one or more atoms. Replacements that match are grouped by class. The class is collapsed; open it to pick one replacement. Selecting the class lists every product from that class. **Add to design list** adds every product shown for that class or replacement. Double-click one product to add only that product. The sketch stays unchanged.
- **Design list** — suggestions and bioisosteric replacements for this session. **Add suggestions** reads the last MMP run and the table's R-group columns and appends new analogs. A row already on the list is not added again. Click a row to put that structure on the canvas. MMP rows with a small structural change and a large activity shift are marked **activity cliff**, with a SALI value, so the median is not treated as a smooth trend. R-group rows are one-substituent swaps, scored as the reference activity plus the difference in substituent means. Each suggestion also shows the druglike MPO. **Send to table** adds the selected rows to the main table. **Remove** drops the selected rows from the list.
- **Properties** — sit beside the canvas, in the same row as the tool rail. The table lists MW, LogP, TPSA, QED, rotatable bonds, and hydrogen-bond donors and acceptors. The score column is the 0–1 desirability, and only that column is colored. The combined druglike score is that column’s geometric mean.
  - **MW** is 1 at or below 350 and 0 at or above 500.
  - **LogP** is 1 at 2.5 and 0 outside 0–5.
  - **TPSA** is 1 at 75 and 0 outside 20–140.
  - **QED** is 0 at or below 0.3 and 1 at or above 0.7.
  - **Rotatable bonds** are 1 at or below 5 and 0 at or above 10.
- **Ionization** — LogD, pKa, CNS MPO, and AB-MPS. A fast estimate appears first. Uni-pKa replaces LogD, CNS MPO, and AB-MPS when it finishes, and fills pKa. CNS MPO (0–6) and AB-MPS sit in the score column on their own scales.
- **Design** on the SAR Matrix — open the selected cell. A filled cell loads that row. An empty or predicted cell builds the analog.

## Workflow

1. Open **Tools → Design Studio**, or right-click a structure cell and choose **Open in Design Studio**. It opens in its own window. The table row stays unchanged. Undo, copy, paste, and delete edit the sketch. The other application shortcuts, such as open, save, and search, still run.
2. Draw or edit. The strip refreshes shortly after each change.
3. **Add suggestions** for MMP and R-group ideas. **Chemistry → Bioisosteric Replacement** adds replacements for the selected atoms. Click a row to inspect it on the canvas.
4. Select the designs you want and **Send to table**. The others stay on the list.
5. From a SAR Matrix, click an empty or predicted cell. **Design** sends the selected cell, including one that already has a compound.

## Use cases

- Check MW, LogP, TPSA, and QED while drawing a single change.
- Turn a missing R1 × R2 cell into a structure you can edit and then add to the table.
- Open a made analog from the grid and adjust it without hunting the row in the sketcher menu.

## Tips and limits

The druglike score is a fixed profile, not the criteria from **Data → MPO Scoring**. A property outside its gate makes the geometric mean zero. Suggestions need a finished **Data → MMP** run, or R-group columns from core-based decomposition plus one numeric activity column. The sketch has to match a row in that series before an R-group swap is offered. There is no stored QSAR model to score a structure that is not in the table. Sending a design that is already a table row does not add a second copy. Building a SAR cell needs one shared Core SMILES and R-group labels that each contain an attachment point. pKa stays blank when Uni-pKa cannot assign a value; the other scores keep the fast estimate.
