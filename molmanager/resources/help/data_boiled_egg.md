# BOILED-Egg

BOILED-Egg shows a brain/intestinal absorption-style plot from molecular properties, with selection helpers for egg and yolk regions.

## Goal

Visualize estimated absorption/BBB-relevant space for the scoped library using the classic egg graphic.

## When to use

Use during early ADME-minded triage when WLOGP/TPSA-style descriptors are available.

## Inputs / scope

Structures/properties required by the plot for rows in scope; **Selected Rows Only** optional. Color-by overlays supported.

## Options

- **Selected Rows Only**.
- **Structure from**.
- **Color by**, **Spectrum**, **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **Egg** / **Yolk** region select.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. Compute needed descriptors if missing.
2. Open **Data → MedChem Plots → BOILED-Egg plot** and set structure source/color.
3. Inspect points in white/yolk regions. Counts (in scope, GIA, BBB, skipped rows) are written to the in-app Log.
4. Use region select actions to push rows back to the table selection.

## Use cases

- Triage CNS-leaning vs peripheral-leaning sets.
- Color by potency inside the egg.
- Select yolk compounds for a focused export.

## Tips and limits

The plot is a heuristic model visualization, not clinical BBB truth. Missing descriptors exclude points. Always pair with experimental ADME when decisions matter. Table filters hide points after Run; coordinates are computed for all rows (or **Selected Rows Only**).
