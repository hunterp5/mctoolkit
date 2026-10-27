# Retrosynthesis

Retrosynthesis plans synthetic routes with a local AiZynthFinder install. Monte Carlo tree search, guided by a neural-network policy, breaks a molecule into precursors and checks them against a stock file on disk.

## Goal

See whether a structure has a solved route in the public USPTO policy and ZINC stock, and record the score, step count, and precursor SMILES on the row.

## When to use

Use **Chemistry → Retrosynthesis → Search** when you want a buyable-precursor route for one molecule or a small set. BRICS and RECAP still split a structure into fragments; they do not search a stock.

## Inputs / scope

A structure column, **Selected Rows Only**, or one pasted SMILES. The Python interpreter and ``config.yml`` come from **Settings → Configure → AiZynthFinder**.

## Options

- **Input** - table rows or a SMILES string.
- **Source** - structure column when the input is the table.
- **Selected Rows Only** - limit the table scope.
- **Policies, filters, and stocks** - the names listed in ``config.yml``. Every policy is on until you clear one. AiZynthFinder would otherwise use only the first policy.
- **Time limit, iterations, maximum reactions, routes to keep** - search limits for this run. The original ``config.yml`` is not rewritten.
- **Algorithm** - Monte Carlo by default. Retro*, breadth-first, and proof-number search are available.
- **Exploration (C)** - how widely Monte Carlo tries less likely reactions.
- **Stop at the first solved route** and **Cluster similar routes** - optional.
- **Search** - queue the job. Cancel keeps rows that already finished.

## Workflow

1. Create a conda environment with Python 3.10–3.12. Leave MolManager's environment alone: AiZynthFinder 4.4.1 requires RDKit 2023.x, and MolManager uses RDKit 2025.9 or newer.
2. In that environment run ``python -m pip install aizynthfinder "pyarrow>=19,<26"``, then ``download_public_data`` into a folder you choose (about 1.8 GB: ONNX models, templates, and ``zinc_stock.hdf5``). AiZynthFinder 4.4.1 stays on NumPy 1.26, and PyArrow 26 will not import on that NumPy.
3. Open **Settings → Configure → AiZynthFinder**, set that environment's ``python.exe`` and the ``config.yml`` next to the model files, and click **Test**.
4. Open **Chemistry → Retrosynthesis → Search**, choose the rows, and run it.
5. Read the ``AiZynth`` columns. They keep the solved state, score, step count, search time, precursor lists, and the other search statistics AiZynthFinder reports, including when the first route was found, the size of the search, and which policies and stocks were used. **Routes…** opens the route tree from that search.

## Use cases

- Check whether a design idea has a solved route in the ZINC stock before enumerating analogs.
- Compare solved-route counts across a short list of candidates.
- Copy in-stock precursor SMILES into a building-block list.

## Tips and limits

A molecule often takes a minute or more. Run a handful of rows, not a whole library, in one job. The same SMILES is searched once and written back to every matching row. Rows that already have AiZynth values are skipped on the next run; clear those cells to search them again.

The job reads the model and stock files named in ``config.yml``. A config with ``use_remote_models: true``, or a MongoDB stock on a host other than localhost, is refused. The search dialog chooses which of those policies, filters, and stocks to use, plus the time limit, iteration limit, maximum number of reactions, and how many routes to keep. Ringbreaker runs when its box is checked. **Routes…** keeps the routes from searches in this session and draws each route as a tree. In-stock molecules have a green frame; molecules that still need a route have an amber frame. Each branch line has a Step button. Click it to show that reaction's policy, probability, template, and other metadata in the table beside the canvas. Right-click a Step button and choose Search Open Reaction Database to look up published conditions for that reaction. Scroll that table to move through long values. Right-click a reaction SMILES or template, or select it and press Ctrl+C, to copy it. Step 1 is the earliest reaction and the highest number is the step that makes the target. A log under the canvas repeats the route, its scores, and its metadata. Center-click and drag to move the drawing in any direction, including past the edges of the canvas. Scroll the wheel to zoom in and out around the pointer. The target sits on the right and its precursors branch to the left. Right-click a card and choose Copy for SMILES or another structure format.
