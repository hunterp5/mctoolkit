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
- **Random number** — Tools → Utilities → Random → Number. Later steps use `${stepId.output}`.
- **Extract reaction** — Chemistry → Reaction → Extract Reaction Info. Later steps use `${stepId.col_1}`, `${stepId.col_2}`, and so on, in the order the columns were written.
- **Plot** — the plotter's axes, color, spokes, and limits. Zoom and pan are not saved. **Add plot** stores the open plotter.
- **Potency** — Tools → Utilities → Potency Standardization. Later steps use `${stepId.activity}`, and `${stepId.p}`, `${stepId.ki}`, or `${stepId.pki}` when those columns were written.
- **R-group enumeration** — a core and building-block lists. Products are added to the table.
- **Add explicit hydrogens**, **Remove explicit hydrogens**, and **Neutralize** — Chemistry → Structure Preparation → Preparation Menu. Later steps use `${stepId.output}` for the structure column that was updated. Render 2D does not delay the next step.
- **Fast prepare** — largest fragment, optional neutralize, and the fragments column. Later steps use `${stepId.output}` and `${stepId.fragments}`.

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

## Recording

**Record** starts a recipe named Recording. Accept a supported tool dialog and the settings are appended when the job finishes. Supported tools are Calculate Descriptors, Calculator, Protonate, Reaction Enumeration, Random Number, Extract Reaction Info, Potency Standardization, R-group enumeration, explicit hydrogens, Neutralize, and Fast Prepare. **Add plot** appends the open plotter. A column written by an earlier recorded step is stored as `${stepId.key}`, so the same recipe works on another table. **Stop recording** leaves the recipe in the list to edit and run. Playing a macro does not record those steps again. Cancelling a dialog adds nothing.

## Limits

This does not record menu clicks, zoom, or pan. The sketcher, docking, protein preparation, and plots other than the plotter are not steps. Render 2D on a protonate step draws in the background and does not delay the next step.
