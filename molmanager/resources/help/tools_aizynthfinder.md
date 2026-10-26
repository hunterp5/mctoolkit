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
- **Search** - queue the job. Cancel keeps rows that already finished.

## Workflow

1. Create a conda environment with Python 3.10–3.12. Leave MolManager's environment alone: AiZynthFinder 4.4.1 requires RDKit 2023.x, and MolManager uses RDKit 2025.9 or newer.
2. In that environment run ``python -m pip install aizynthfinder``, then ``download_public_data`` into a folder you choose (about 1.8 GB: ONNX models, templates, and ``zinc_stock.hdf5``).
3. Open **Settings → Configure → AiZynthFinder**, set that environment's ``python.exe`` and the ``config.yml`` next to the model files, and click **Test**.
4. Open **Chemistry → Retrosynthesis → Search**, choose the rows, and run it.
5. Read the ``AiZynth`` columns: solved, solved-route count, score, steps, search time, and precursor SMILES in and out of stock.

## Use cases

- Check whether a design idea has a solved route in the ZINC stock before enumerating analogs.
- Compare solved-route counts across a short list of candidates.
- Copy in-stock precursor SMILES into a building-block list.

## Tips and limits

A molecule often takes a minute or more. Run a handful of rows, not a whole library, in one job. The same SMILES is searched once and written back to every matching row. Rows that already have AiZynth values are skipped on the next run; clear those cells to search them again.

The job reads the model and stock files named in ``config.yml``. A config with ``use_remote_models: true``, or a MongoDB stock on a host other than localhost, is refused. This search writes summary columns. It does not draw the route tree.
