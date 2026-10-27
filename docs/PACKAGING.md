# Packaging molmanager for distribution

This document supports building an installer (PyInstaller, Inno Setup, MSI, etc.) so users can run molmanager without managing Python manually.

## Install profiles

| Profile | Command | Use when |
|---------|---------|----------|
| **Core desktop** | `pip install -r requirements-core.txt` then `pip install -e ".[dev]"` | Table/filter/plot work; smaller CI / laptops |
| **Full (default docs)** | `pip install -r requirements.txt` then `pip install -e .` | pKa, permeability, docking helpers, and torch |
| **Extras only** | `pip install -e ".[pka,permeability,docking,conforge,dev]"` after a matching torch | Editable workflows that already have a CUDA/CPU torch |

`requirements.txt` remains the one-shot “install everything” path. Prefer **core** when you do not need ML tools.

## What is included

| Component | How it ships |
|-----------|----------------|
| molmanager app (`molmanager` package) | PyInstaller one-folder/one-file, or `pip install -e .` |
| Python dependencies | `requirements-core.txt` or `requirements.txt`, then `pip install -e .` |
| 3Dmol.js | Already in `molmanager/ui/static/` |
| AutoDock Vina | **Optional** binary in `molmanager/resources/bin/<platform>/` (not redistributed in git) |

## Recommended install commands (source / CI)

Core (recommended for most desktop development):

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -U pip
pip install -r requirements-core.txt
pip install -e ".[dev]"
```

Full stack (PyTorch, unipkainfer, Chemprop, Meeko, pytest):

```bash
pip install -U pip
pip install -r requirements.txt
pip install -e .
```

The pKa install script selects CUDA automatically when `nvidia-smi` sees a GPU (`-Cpu` / `--cpu` keeps the CPU wheel):

```bash
# Windows
scripts\install_pytorch_pka.ps1
# macOS / Linux
bash scripts/install_pytorch_pka.sh
```

Editable install with extras (optional):

```bash
pip install -e ".[pka,permeability,docking,conforge,dev]"
```

## Bundling external tools

1. Run `scripts\bootstrap_optional_tools.ps1` (Windows) or `scripts/bootstrap_optional_tools.sh` (Linux/macOS) to install Python deps, swap in CUDA PyTorch when an NVIDIA GPU is present, and print where to place a Gnina binary.
2. On Linux, copy `gnina` into `molmanager/resources/bin/linux/` (or set `MOLMANAGER_BUNDLE_DIR`). On Windows, install Gnina in WSL so `gnina` is on that distro’s PATH (Settings → Configure → WSL), or set the binary under Settings → Configure → Gnina.
3. Protein → Dock Ligand defaults to bundled paths when present.

## PyInstaller (starter)

A minimal spec lives in `packaging/molmanager.spec`. Build (from repo root, venv activated):

```bash
pip install pyinstaller
pyinstaller packaging/molmanager.spec
```

Output under `dist/molmanager/`. UPX is off in the spec. `codesign_identity` stays unset until a signing certificate is available, and CI does not build this artifact yet. You still need to ship:

- Qt platform plugins (PyInstaller usually collects these)
- Optional `resources/bin/` for Gnina

Tune `packaging/molmanager.spec` hidden imports as you enable more Tools menu features.

For **enterprise single-user desktop** builds, prefer a **core** PyInstaller image (no torch/chemprop) unless the product SKU explicitly includes pKa/permeability. Keep ML tools as an optional second installer or documented pip extras.

## Version and release policy

Keep these three values in sync on every tagged release:

1. `molmanager.__version__` in `molmanager/__init__.py`
2. `[project].version` in `pyproject.toml`
3. Git tag: `vX.Y.Z` (annotated) matching that version

Process:

1. Bump both version fields together (no silent drift).
2. Run the performance gate below on a machine representative of target hardware.
3. Tag `vX.Y.Z` on `main` after merge from `dev`.
4. Attach installer artifacts (if any) to the GitHub Release for that tag; note core vs full profile in the release notes.

Application version is shown in About when wired to `molmanager.__version__`.

## Performance release gate (100k rows)

Run before tagging a production build:

```bash
python scripts/benchmark_large_table.py --runs 3 --scales 10000,50000,100000
python scripts/perf_gate.py
pytest tests/test_compound_table_model_batch.py tests/test_sqlite_table_store.py tests/test_substructure_filter_worker.py -q
```

Target SLA guidance for enterprise-ready builds on a typical developer workstation:

- 100k row batch ingest to model: p95 under 5s
- Numeric bounds scan on 100k rows: p95 under 3s
- In-memory sort on 100k rows: p95 under 2s
- Substructure filter should use prebuilt mol targets (no per-row reparsing in worker)

If any metric regresses by more than 20% against your previous release baseline, block release and investigate.
