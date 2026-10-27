# REINVENT Learning

REINVENT Learning runs one reinforcement-learning stage with a local **REINVENT 4** install and appends the best molecules to the table.

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
- **Penalize repeated scaffolds** - an identical Murcko scaffold is memorized after 25 molecules score above 0.4. Further copies are penalized.
- **Save agent** - copy the learned checkpoint. Blank discards the agent after the molecules are added.
- **Combine** - geometric mean or arithmetic mean of the score terms.
- **Scaffold** - optional SMARTS. The agent is rewarded for molecules that contain it, and only those matches are appended. **Sketcher…** draws the pattern. For R-groups, a pattern with `*` is also the scaffold that gets decorated.
- **QED**, **Molecular weight**, **SlogP**, **SA score** - each can be turned on. Weight and SlogP use a window; outside that window the term falls toward zero. SA score favors values near 2 and penalizes values of 5 and above.
- **Similarity** - Morgan fingerprints, radius 2, against each reference. Each reference is its own term.
- **Drop REINVENT's unwanted groups** - the published SMARTS filter. A match scores zero. **More SMARTS** adds patterns, one per line.
- **Keep best** - how many unique molecules to append. The same molecule is stored once, at its highest score.

## Workflow

1. Set **Settings → Configure → REINVENT** if sampling has not already done that.
2. Open **Chemistry → REINVENT → Learning**.
3. Pick the generator, model, and scores. For anything except de novo, choose seeds.
4. Click **Learn** and leave the dialog open. **Stop** ends the process and still adds molecules written so far.
5. Rows arrive with **REINVENT_Score**, **REINVENT_Step**, the generator, the model, and the component scores.

## Use cases

- Start from `.reinvent` and prefer drug-like molecules between 200 and 500 Da.
- Add a similarity term so the agent stays near a selected lead.
- Decorate a scaffold while the score prefers a molecular-weight window.

## Tips and limits

A short run is 25 steps. Raising the step count is what makes the agent move. A run that would score more than 20,000 SMILES asks before it starts. CPU learning is much slower than a GPU. Closing the dialog stops the run. This is one stage, not a curriculum, and it does not call docking or a QSAR model.
