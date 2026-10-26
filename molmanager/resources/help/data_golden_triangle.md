# Golden Triangle

Golden Triangle displays a medchem golden-triangle style plot to relate key properties associated with developability heuristics.

## Goal

See which molecules fall into a historically favored property region for oral small molecules.

## When to use

Use alongside other property plots when optimizing potency vs simple physicochemical limits.

## Inputs / scope

Requires the property/structure inputs the plot expects; scope via **Selected Rows Only** as needed.

## Options

- **Selected Rows Only**.
- **Structure from**.
- **Color by**, **Spectrum**, **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **Triangle** region select.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. Ensure descriptor columns used by the triangle exist.
2. Open **Data → MedChem Plots → Golden Triangle** and configure source/color.
3. Review in-triangle vs outside compounds. The in-scope and in-triangle counts are written to the in-app Log.
4. Use **Triangle** to focus follow-up tools.

## Use cases

- Check whether potent hits still sit in a preferred property band.
- Color by series/cluster inside the triangle.
- Export in-triangle selection for discussion.

## Tips and limits

Heuristic guidance only - many successful drugs sit outside cartoon regions. Descriptor errors move points misleadingly. Use with MPO rather than as a hard gate alone. Table filters hide points after Run; coordinates are computed for all rows (or **Selected Rows Only**).
