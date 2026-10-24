# Protonate

Protonate writes the dominant protomer at a chosen pH into an output column using a **Uni-pKa** ionization ensemble (MolGpKa SMARTS enumeration + Uni-Mol free energies). It also writes **% Protomer (pH …)** with the dialog pH in the header, the Boltzmann mole fraction of that form at that pH, and **pKa** (macro pKa list, same column as Predict pKa). Optional **Render 2D** depicts that column the same way as **Structure** (image cells; SMILES stay stored, not shown as text). Right-click a Protonated cell for Open in Sketcher, Browser, Render 2D, **Copy** (SMILES, InChI, InChIKey, Molfile, SMARTS), and Paste.

## Goal

Produce pH-relevant ionization states for permeability-minded prep, docking ligands, or consistent descriptor calculation.

## When to use

Use when default microstates are wrong for your assay pH, or before comparisons that depend on charge state. For the full ensemble at that pH, use **Generate Protomers** instead.

## Inputs / scope

Input structures from the selected source; optional **Selected Rows Only**. Requires Uni-pKa (`unipkainfer`). Duplicate structures are predicted once and reused; a session cache is shared with Predict pKa and LogD/LogS so a second run on the same molecules is cheap. Unique structures are scored in batches of up to 16, and the one-worker CUDA process stays loaded between jobs. Saved ``.cms`` sessions restore that cache on Open / Duplicate.

## Options

- **Structure source** - which structure column to read.
- **pH** - target pH for dominant protomer selection.
- **Output column** - destination column name. A companion **% Protomer (pH …)** column records the population at this pH, and **pKa** lists the Uni-pKa macros (shared with Predict pKa / LogD).
- **Selected Rows Only** - limit to the selection.
- **Render 2D in output column** - depict the output column like **Structure** (pixmap cells). Unchecked leaves SMILES text.
- **Run** - start the job.

## Workflow

1. Set structure source, **pH**, and output column.
2. Choose full table or **Selected Rows Only**.
3. Run and wait for completion.
4. Point later tools at the output column as structure source. Check **% Protomer (pH …)** if the top form is only a slim majority.

## Use cases

- Protonate at pH 7.4 before medchem property plots.
- Prepare ligands at physiological pH for docking.
- Compare acidic vs basic series at a shared pH.

## Tips and limits

Populations are Boltzmann weights of Uni-pKa free energies at the dialog pH (not independent-site Henderson–Hasselbalch). **% Protomer (pH …)** below ~80% means other forms still matter; use **Generate Protomers**. **pKa** is the same shared column as Predict pKa (updated in place). For **pI**, use Predict pKa with **Calculate isoelectric point**. The Uni-pKa ensemble is stored in the session cache (including each protomer SMILES) so later pKa-dependent tools do not re-run inference. Parallelism is `MOLMANAGER_PROTOMER_PROCESSES` (`1`–`8`). Always keep the original column if you need neutral parents. Re-running after pkasolver is a new method, not a refresh. Cancelling writes whatever rows already finished.
