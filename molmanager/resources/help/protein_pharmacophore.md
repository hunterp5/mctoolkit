# Pharmacophore

Build a 3D pharmacophore in Protein Viewer, save it as its own file, and apply it when docking with Gnina.

## Goal

Mark sites in the pocket (H-bond donors and acceptors, aromatic centroids, hydrophobes, and other RDKit BaseFeatures families) so later docking runs prefer those regions.

## When to use

Use **Protein Viewer → Tools → Pharmacophore** after a structure is on the canvas and you want reusable spatial constraints. Use **Protein → Dock Ligand → Gnina → Pharmacophore** to keep docked poses that occupy those spheres. Use **Chemistry → Conformations → Screen Pharmacophore** (or **Protein Viewer → Tools → Pharmacophore → Screen Table…**) to find table molecules whose ensembles match the same feature pattern.

## Inputs / scope

Features are spheres in Cartesian coordinates (Å). Each site has a feature family and an optional **atom** (C, N, O, …). Click an atom to fill X/Y/Z and the element, then **Add**, or type coordinates and pick **Atom** yourself. **Any** matches every element. Empty canvas space is not pickable in 3Dmol. You can also generate sites from a ligand with RDKit.

The file format is JSON (`molmanager.pharmacophore` version 1), typically `.json` or `.mph4`. It is independent of the MolManager session file; **Save…** writes it for other sessions.

Gnina does not have a native pharmacophore constraint. MolManager docks with CNN/Vina as usual, then **filters poses in the protein frame**: each enabled attractive site must have an RDKit ligand feature of the same type inside its sphere (plus **Slack**). If **Atom** is set, that ligand site must be the same element. **Exclusion** sites reject a pose if a ligand heavy atom (of that element, or any heavy atom when Atom is **Any**) is inside. Occupancy `--user_grid` maps are not used (Gnina’s `--user_grid_lambda` would scale Vina, not “weight the pharmacophore”).

## Options

The **Tools → Pharmacophore** menu is **Editor**, **Screen Table…**, and **Open…**. Placement, ligand sites, save/clear, and **Send to Gnina** live in the editor.

- **Editor** — table of features (id in the row header, type, atom, X/Y/Z, radius, on/off) and placement controls. Click a row header to select that feature. Colored spheres appear on the canvas while the editor is open and are removed when it closes.
- **Add** — in the editor; insert at the current X/Y/Z (Å). Click an atom in the canvas first to fill those coordinates and the atom type.
- **Type** — RDKit BaseFeatures families: H-bond donor, H-bond acceptor, aromatic, hydrophobe, lumped hydrophobe, positive/negative ionizable, zinc binder, plus **Exclusion**.
- **Atom** — optional element (C, N, O, …). **Any** (default) matches every element. Clicking a canvas atom fills this. **From ligand** copies the unique heavy-atom element when RDKit reports one.
- **Radius** — sphere radius in Å used when matching docked poses (plus Gnina **Slack**).
- **From ligand** — next to **Add** in the editor; RDKit `BaseFeatures.fdef` sites from the selected ligand (or every ligand if none is selected).
- **Open…** — load a pharmacophore JSON (menu or editor).
- **Save… / Clear** — in the editor; write the JSON or remove all features from this viewer.
- **Send to Gnina** — in the editor; write the file if needed and fill the Gnina **Pharmacophore** field.
- **Screen Table…** — open **Chemistry → Conformations → Screen Pharmacophore…** with this pharmacophore against packed `confs` / `superpose` / `poses`.
- **Gnina → Pharmacophore / Slack** — path to the JSON and extra match tolerance (default 0.50 Å). Docked poses that miss a required sphere are dropped.

## Workflow

1. Open **Protein → Viewer** and load a complex.
2. Choose **Tools → Pharmacophore → Editor**.
3. Click an atom to fill X/Y/Z and **Atom**, then **Add**, or **From ligand**. Adjust type, atom, and radius in the table.
4. **Save…** the pharmacophore for reuse.
5. **Send to Gnina** (or browse the file in the Gnina dialog) and run docking as usual.
6. To find analogs in the compound table, generate conformers, then **Screen Table…** (or **Chemistry → Conformations → Screen Pharmacophore…**).

## Use cases

- Recapitulate a crystal ligand’s donors, acceptors, and aromatic centroid, then dock analogs and keep poses that occupy those same sites.
- Add an **Exclusion** sphere to keep poses out of an unproductive subpocket.
- Reload a saved pharmacophore in a later session without rebuilding the viewer layout.
