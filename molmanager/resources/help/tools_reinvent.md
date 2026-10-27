# REINVENT Sampling

REINVENT Sampling draws molecules with a local **REINVENT 4** install and opens them in a new table.

REINVENT Sampling proposes structures from a fixed model. To optimize that model against scores, use REINVENT Learning. Transfer learning stays on the REINVENT command line.

## Goal

Get a set of SMILES from a pretrained generator: new molecules, R-groups on a scaffold, a linker between two fragments, or molecules similar to a seed.

## When to use

Use when you want ideas from a generative model and then keep working with them in the table. R-group enumeration is the better tool when you already have a reagent list. Reaction enumeration is the better tool when the bond change is a named reaction.

## Inputs / scope

REINVENT 4 installed in **its own** Python environment. MolManager's environment cannot host it. Set the `reinvent` command under **Settings → Configure → REINVENT**. A blank path uses `reinvent` on PATH.

De novo sampling needs no table rows. The other generators need seeds from the selection, from every row, or from pasted SMILES.

## Options

- **Generator** - De novo (Reinvent), R-groups (LibInvent), Linker (LinkInvent), or Similar molecules (Mol2Mol).
- **Model** - a prior id, such as `.reinvent`, or a path to a `.prior` file. **Browse...** picks a file. The preset list fills the box with the id for that generator. Those ids are the names in the REINVENT install's prior registry, and they resolve to files in that install's `priors` folder. A path works when the file lives somewhere else.
- **Device** - `cpu`, or `cuda:0` when the REINVENT environment has an NVIDIA GPU.
- **Molecules** / **Samples per seed** - how many SMILES to draw. For every generator except de novo, this count is applied to each seed.
- **Sampling** - multinomial (random) or beam search (deterministic, more memory). Shown for LibInvent, LinkInvent, and Mol2Mol.
- **Temperature** - Mol2Mol only. 1.0 is the model default.
- **Unique molecules** - drop duplicate canonical SMILES.
- **Randomize seed SMILES** - shuffle atom order in the seeds before sampling.
- **Random seed** - fixes the draw. **Auto** leaves REINVENT's seed unset.
- **Keep stereochemistry in SMILES** - write isomeric SMILES. Off is REINVENT's default.
- **Extra flags** - more `reinvent` options, such as `--log-level debug` or `--log-filename`. `--device` and `--seed` here override the fields above.
- **Seeds** - selected rows, all rows, or pasted SMILES (one per line). LibInvent scaffolds need an attachment point (`*`). LinkInvent lines look like `fragment|fragment`, and each fragment needs `*`. A cell that already contains `|` or `*` is sent as written.
- **Scaffold** - optional SMARTS. Only molecules that contain it are opened. **Sketcher…** draws the pattern, including `*` attachment points. For R-groups, a pattern that contains `*` is also used as the scaffold to decorate, so the seed list can stay empty.

## Workflow

1. Install REINVENT 4 in a separate environment and set **Settings → Configure → REINVENT**. **Test** runs `reinvent -V`.
2. Open **Chemistry → REINVENT → Sampling**.
3. Pick the generator and model. For anything except de novo, choose seeds.
4. Click **Sample** and leave the dialog open. Output is written in the log. **Stop** ends the process.
5. Valid SMILES open in a new MolManager table with **REINVENT_NLL**, **REINVENT_Generator**, **REINVENT_Model**, and **REINVENT_Seed** when a seed was reported. This table is unchanged until you click **Add to this table**.

## Use cases

- Draw 50 de novo molecules from the public Reinvent prior and inspect them in the table.
- Decorate one scaffold that has a `*` attachment point.
- Propose linkers between a pair of fragments.
- Ask Mol2Mol for molecules similar to the selected rows.

## Tips and limits

The priors are files next to the REINVENT install (`priors\reinvent.prior` and the LibInvent, LinkInvent, and Mol2Mol files). Public copies are on Zenodo (doi:10.5281/zenodo.15641296). CPU sampling is slower than a GPU. A run that would draw more than 20,000 SMILES asks before it starts. SMILES RDKit cannot read are counted in the log and are not opened. Closing the dialog stops the run. This does not train a model or call REINVENT's scoring plugins. Reinforcement learning is Chemistry → REINVENT → Learning.
