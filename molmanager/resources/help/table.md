# Table

The compound table is the central grid of structures and properties: columns, sorting, context menus, numeric precision, and row selection drive almost every tool.

## Goal

Organize and inspect molecules so filters, plots, and models operate on the right columns and rows.

## When to use

Use continuously while analyzing; revisit this topic for sorting, column management, and selection behavior.

## Inputs / scope

All loaded rows and columns in the session. Structure columns supply depictions and chemistry; numeric/text columns supply plots and models.

## Options

- **Column headers** - sort and header context actions.
- **Row selection** - single or multi-select for scoped tools.
- **Context menus** - column/row operations and related actions. Header **Select → Select All** selects currently visible rows only. **First Occurrence** and other header Select actions are cleared by plot **Clear Selection** and **Edit → Clear Selection**. Right-click a text cell and choose **Edit Value…** or **Clear Value** to change it (double-click does not open an editor). Structure cells and tool-generated structure columns (for example **Protonated** after Render 2D) offer Open in Sketcher, Browser, Render 2D, **Copy** (SMILES, InChI, InChIKey, Molfile, SMARTS), and Paste. **Browser** opens the selection browser (RDKit 2D, 3Dmol 2D, or 3Dmol 3D in Browser settings). **Duplicate** on the Structure header copies molecules into a new chemistry column you can rename, delete, and use as a tool source.
- **Structure cells** - 2D depictions from the active render cache.
- **Precision / display** - numeric presentation controls where offered.

## Workflow

1. Load data and confirm structure columns render.
2. Sort or rearrange columns for the task.
3. Select rows or apply filters/search.
4. Launch tools that write new columns back into the table.

## Use cases

- Sort by score then select top-N for export.
- Keep descriptor columns beside assay columns for QSAR setup.
- Use precision controls before screenshots or reports.

## Tips and limits

Sorting does not by itself change chemistry - only order. Invalid molecules show empty/failed depictions and fail structure tools. Wide tables are easier if you hide unused columns when the UI allows. Drag a column's right border to resize it; if that border sits at the edge of the window, grab the right edge of the table (pixel scrolling keeps the column on screen).
