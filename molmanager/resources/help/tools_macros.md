# Macros

Macros run a saved sequence of table tools. Tools → Macros… edits the library and runs the selected macro on the current table.

## Goal

Repeat a preparation you already do by hand: calculate a few descriptors, derive a column, keep the rows you want, protonate what remains, or enumerate a reaction.

## What a macro can do

Each step is one of:

- **Calculate descriptors** — the same descriptors as Chemistry → Calculate Descriptors, chosen by their internal key (`MolWt`, `MolLogP`), not the column title (`Mol Weight`).
- **Calculator** — a numeric expression. Bracket column names (`[MolWt]`). The new column is `${stepId.output}` for later steps.
- **Filter** — numeric range, text, or substructure cards. By default this replaces the filter panel. A numeric card uses that column's current data range, the same way a filter card does.
- **Protonate** — dominant protomer at a pH. Later steps can use `${stepId.output}`, `${stepId.percent}`, and `${stepId.pka}`.
- **Reaction enumeration** — a two-reactant reaction from SMILES lists or files. Products can be added to the table or saved to an SDF.

## Rows

Descriptor, calculator, and protonate steps choose **All rows**, **Selected rows**, or **Visible rows**. A filter step changes which rows are visible, so a later step set to visible rows sees that subset.

## Column references

A step id is the short name on the step (`desc1`, `calc1`). A later step refers to a column that earlier step wrote:

- `${desc1.MolWt}` — the MolWt column from that descriptor step, even if the header was renamed to `Mol Weight (1)`
- `${calc1.output}` — the calculator column
- `${prot1.output}` — the protonated structure column

References only point at earlier steps.

## Run

Save stores the library on this machine, separate from the session file. Run checks the recipe, then plays the steps in order. The next step starts after the previous step's columns or filters are in place. Stop cancels the running tool and does not start the rest.

Do not start another chemistry tool while a macro is running. The recipe is waiting on that tool's result.

## Limits

This does not record menu clicks. Plots, the sketcher, docking, and protein preparation are not steps. Render 2D on a protonate step draws in the background and does not delay the next step.
