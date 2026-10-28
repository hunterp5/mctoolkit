# Predict Metabolites

Predict Metabolites runs **BioTransformer 3** on a local Java JAR to enumerate likely **metabolite structures** (products of CYP450, Phase II, gut, or combined human metabolism).

BioTransformer proposes metabolite product structures.

## Goal

See first-generation (or short multi-step) metabolites of table compounds on this machine.

## When to use

Use when you need candidate metabolite SMILES for design, MS annotation, or soft-spot follow-up.

## Inputs / scope

Rows with valid molecules in the chosen structure **Source**, or a single **SMILES string**. Optional **Selected Rows Only**. Requires **Java on PATH** and a BioTransformer 3 install (JAR plus sibling `btkb/` or `database/` and `supportfiles/`).

Install steps for Java and the JAR are in **External tools**. Run `python scripts/bootstrap_biotransformer.py`, use **Settings → Configure → BioTransformer** (**Browse JAR…** / **Install…**), or set `MOLMANAGER_BIOTRANSFORMER_JAR`. Java is **Settings → Configure → Java** when it is not on PATH. Official docs target UNIX; on Windows try a current JRE, or run the JAR under WSL.

## Options

- **Input** - table rows or a SMILES string.
- **Source** - structure column to read (table mode).
- **Selected Rows Only** - limit to the current selection.
- **Metabolism** - Human (tissues + gut) (default), CYP450, Phase II, EC-based, Human gut microbial, or SuperBio. Environmental microbial is not offered.
- **Steps** - 1–3 biotransformation generations (default 1). Extra steps multiply products quickly.
- **CYP mode** - CypReact + rules, CyProduct only, or Combined (CYP450 / AllHuman only).
- **Max metabolites** - cap kept per parent.
- **Add metabolites as new table rows** - off by default; when on, each product is appended with Parent SMILES, Reaction, Enzyme, and Generation.
- **Predict** - queue the background job.

## Workflow

1. Install Java and the BioTransformer JAR layout.
2. Choose table rows or paste SMILES.
3. Pick metabolism, steps, and the product cap.
4. Run **Predict** and wait on **Processes**.
5. Review parent columns (**Metabolite Count**, **Metabolite Reactions**, **Metabolite SMILES**) and the **Predict Metabolites Browser**. The table lists the parent first, then metabolites (structure, reaction, enzyme, step); click a row to show that structure on the canvas. **Browse Only Selected** is in the footer. Reopen it from **Chemistry → Predict → Metabolites → Viewer**. A saved session keeps the browser records (reaction, enzyme, generation, and every product SMILES), so Viewer shows the same results after Open. Parent-row columns alone keep a shorter SMILES list when no browser records were saved.

## Use cases

- List CYP oxidation products of a lead.
- Compare Phase II conjugates after a one-step run.
- Append metabolites as new rows for further descriptors or docking.

## Tips and limits

Identical parents are predicted once. Each unique molecule is one JAR call. SuperBio and extra steps are slow. PubChem annotate is not used. Commercial redistribution of BioTransformer files needs permission from the authors. If the JAR fails on native Windows, use WSL rather than the public web API (one molecule and two POSTs per minute).
