# REINVENT Learning

REINVENT Learning runs one reinforcement-learning stage with a local **REINVENT 4** install and opens the best molecules in a results browser.

The agent starts from a prior, samples a batch, scores it, and updates itself. That repeats until the step limit or the stop score. MolManager then keeps the highest-scoring unique SMILES.

## Goal

Bias a generator toward molecules that score well on drug-likeness, a property range, similarity to references, or a combination of those.

## When to use

Use when sampling from the prior is not selective enough. REINVENT Sampling is the better tool when you only want draws from a model that is already trained. Transfer learning is not in this dialog.

## Inputs / scope

The same REINVENT 4 command as sampling: **Settings → Configure → REINVENT**. The prior ids are files in that install's `priors` folder.

De novo learning needs no seeds. R-group, linker, and similar-molecule generators need seeds from the selection, from every row, or from pasted SMILES.

Scores are RDKit components that ship with REINVENT: QED, molecular weight, SlogP, synthetic accessibility, Tanimoto similarity, and SMARTS alerts. Docking, ChemProp, and OpenEye scores are not in this dialog.

## Options

- **Generator** and **Model** - same choices as REINVENT Sampling. The model is both the prior and the starting agent.
- **Device** - `cpu`, or `cuda:0` when the REINVENT environment has an NVIDIA GPU.
- **Sampling**, **Temperature**, **Distance** - Mol2Mol only. Distance penalizes molecules far from the seeds.
- **Batch size** - molecules scored at each step. 64 is REINVENT's default.
- **Max steps** / **Min steps** - the stage stops at the maximum. It can stop earlier, after the minimum, when the mean score reaches **Stop score**.
- **Sigma** and **Learning rate** - DAP reward scale and Adam step size. 128 and 0.0001 are REINVENT's defaults.
- **Penalize repeated scaffolds** - on by default. **Filter** chooses identical Murcko scaffolds, topological scaffolds, similar scaffolds, or the same SMILES. **Bucket size** and **Min score** are 25 and 0.4 for the scaffold filters. Similar scaffolds also use **Min similarity**. Same SMILES uses **Penalty**.
- **Random seed** - fixes the run. **Auto** leaves REINVENT's seed unset.
- **Keep stereochemistry in SMILES** - write isomeric SMILES. Off is REINVENT's default.
- **Extra flags** - more `reinvent` options, such as `--log-level debug` or `--log-filename`. `--device` and `--seed` here override the fields above.
- **Save agent** - copy the learned checkpoint. Blank discards the agent after the molecules are shown.
- **Combine** - geometric mean or arithmetic mean of the score terms.
- **Scaffold** - optional SMARTS. The agent is rewarded for molecules that contain it, and only those matches are shown. **Sketcher…** draws the pattern. For R-groups, a pattern with `*` is also the scaffold that gets decorated.
- **QED**, **Molecular weight**, **SlogP**, **SA score** - each can be turned on, with a **weight**. Molecular weight and SlogP use a window; outside that window the term falls toward zero. SA score favors values near 2 and penalizes values of 5 and above.
- **Similarity** - Morgan fingerprints against each reference. **Radius**, **Counts**, and **Features** set the fingerprint. Each reference is its own term, and **weight** applies to each of them.
- **Drop REINVENT's unwanted groups** - the published SMARTS filter. A match scores zero. **More SMARTS** adds patterns, one per line.
- **Keep best** - how many unique molecules to show. The same molecule is stored once, at its highest score.

## Workflow

1. Set **Settings → Configure → REINVENT** if sampling has not already done that.
2. Open **Chemistry → REINVENT → Learning**.
3. Pick the generator, model, and scores. For anything except de novo, choose seeds.
4. Click **Learn** and leave the dialog open. **Stop** ends the process and still shows molecules written so far.
5. The best rows open in the REINVENT browser with **REINVENT_Score**, **REINVENT_Step**, the generator, the model, and the component scores. **Add to table** copies them into this table.

## Use cases

- Start from `.reinvent` and prefer drug-like molecules between 200 and 500 Da.
- Add a similarity term so the agent stays near a selected lead.
- Decorate a scaffold while the score prefers a molecular-weight window.

## Tips and limits

A short run is 25 steps. Raising the step count is what makes the agent move. A run that would score more than 20,000 SMILES asks before it starts. CPU learning is much slower than a GPU. Closing the dialog stops the run. This is one stage, not a curriculum, and it does not call docking or a QSAR model.
