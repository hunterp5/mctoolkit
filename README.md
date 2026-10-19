# MolManager

MolManager is a desktop application for working with chemical structures in a spreadsheet-style table. You can open SDF, SMILES, and CSV files; draw structures; calculate descriptors; cluster compounds; dock ligands; and more. It is built with **Python**, **PyQt5**, and **RDKit**.

This guide walks you through installation from scratch. It assumes you are new to Python and the command line. Follow the steps in order for your operating system.

---

## What you will need

| Requirement | Details |
|-------------|---------|
| **Computer** | Windows 10 or later, macOS 10.15+, or a recent Linux distribution |
| **Internet** | Required to download Python, MolManager, and dependencies |
| **Disk space** | About 1–2 GB for a basic install; more if you add optional machine-learning tools (pKa prediction, permeability models) |
| **Python** | Version **3.10**, **3.11**, or **3.12** (**3.11 is recommended**). Do **not** use 3.13 or newer — MolManager pins NumPy 1.x (PyTorch 2.5 / UMAP), and NumPy 1.26 has no Windows wheels for those versions, so pip tries to compile NumPy and fails without Visual Studio |

You do **not** need to know how to program. You will copy and paste a few commands into a terminal window.

---

## Part 1 — Install Python

Python is the language MolManager is written in. You need it installed before anything else.

### Windows

1. Open your web browser and go to [https://www.python.org/downloads/](https://www.python.org/downloads/).
2. Click the yellow **Download Python 3.11.x** button (or the latest 3.11 release).
3. Run the installer.
4. **Important:** On the first screen, check the box that says **“Add python.exe to PATH”** at the bottom. If you skip this, the steps below will not work.
5. Click **Install Now** and wait for it to finish.

**Check that Python installed correctly**

1. Press the **Windows key**, type **PowerShell**, and open **Windows PowerShell**.
2. Type this and press **Enter**:

   ```powershell
   python --version
   ```

   You should see something like `Python 3.11.9`. If you see an error, close PowerShell, reinstall Python, and make sure **Add to PATH** was checked.

### macOS

1. Open **Terminal** (search for it in Spotlight).
2. Check whether Python is already installed:

   ```bash
   python3 --version
   ```

3. If you see `Python 3.10` or `3.11`, you can continue. If not, install Python from [python.org/downloads](https://www.python.org/downloads/) or with Homebrew:

   ```bash
   brew install python@3.11
   ```

### Linux

Most distributions include Python 3. Install it with your package manager if needed, for example:

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install python3 python3-venv python3-pip

# Fedora
sudo dnf install python3 python3-pip
```

Verify:

```bash
python3 --version
```

---

## Part 2 — Download MolManager

You need a copy of the MolManager project on your computer.

### Option A — Download as a ZIP (simplest)

1. Go to the MolManager repository on GitHub.
2. Click the green **Code** button, then **Download ZIP**.
3. Extract the ZIP to a folder you will remember, for example:
   - Windows: `C:\Users\YourName\Documents\MolManager`
   - macOS/Linux: `~/Documents/MolManager`

### Option B — Clone with Git (if you use Git)

```bash
git clone https://github.com/hunterp5/MolManager.git
cd MolManager
```

All remaining steps assume your terminal is **inside the MolManager folder** (the folder that contains `README.md`, `requirements.txt`, and the `molmanager` subfolder).

**Windows — open a terminal in that folder**

1. Open File Explorer and navigate to the MolManager folder.
2. Click the address bar, type `powershell`, and press **Enter**.

   A PowerShell window opens already pointed at the right folder.

**macOS / Linux**

```bash
cd ~/Documents/MolManager
```

(replace the path with wherever you extracted or cloned the project)

---

## Part 3 — What is a virtual environment?

Before installing MolManager, you will create a **Python virtual environment** (often called a **venv**).

Think of it as a private toolbox for this one application:

- All of MolManager’s dependencies are installed **inside** that toolbox.
- They do not mix with other Python programs on your computer.
- You can delete the toolbox (the `.venv` folder) without affecting anything else.

You will create the venv once, activate it whenever you work with MolManager, and install packages into it. The folder is named `.venv` and lives inside the MolManager project directory.

---

## Part 4 — Create the virtual environment

Run **one** of the blocks below depending on your system.

### Windows (PowerShell)

```powershell
python -m venv .venv
```

If `python` is not found, try:

```powershell
py -3.11 -m venv .venv
```

### macOS / Linux

```bash
python3 -m venv .venv
```

This creates a `.venv` folder. It may take a minute. You only need to run this command **once** per project copy.

---

## Part 5 — Activate the virtual environment

You must **activate** the venv every time you open a **new** terminal window before installing or running MolManager. Activation tells the terminal to use the Python inside `.venv`.

### Windows (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
```

If you see an error about running scripts being disabled, run this **once** (as Administrator is not required for your user account):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

**Success looks like this:** your prompt starts with `(.venv)`, for example:

```text
(.venv) PS C:\Users\You\Documents\MolManager>
```

### Windows (Command Prompt)

```cmd
.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Your prompt should show `(.venv)` at the beginning.

> **Remember:** If you close the terminal or open a new one later, run the activate command again before starting MolManager.

---

## Part 6 — Install MolManager and its dependencies

With the virtual environment **active** (`(.venv)` visible in your prompt), run these commands **in order** from the MolManager project folder.

### Step 6a — Upgrade pip

`pip` is Python’s package installer. Upgrading it first avoids many common install errors.

**Windows**

```powershell
python -m pip install --upgrade pip
```

**macOS / Linux**

```bash
python3 -m pip install --upgrade pip
```

### Step 6b — Install dependencies

**Core desktop (recommended if you do not need pKa / permeability / docking ML):** smaller download, no PyTorch.

```bash
pip install -r requirements-core.txt
```

**Full stack:** desktop app plus machine-learning tools (PyTorch, Uni-pKa / unipkainfer, Chemprop), docking helpers (Meeko), and development tools (pytest). It can take **15–30 minutes** depending on your internet speed.

```bash
pip install -r requirements.txt
```

See [docs/PACKAGING.md](docs/PACKAGING.md) for install profiles and release versioning.

### Step 6c — Register the MolManager application

This step installs the MolManager program itself so you can launch it with `python -m molmanager`:

```bash
pip install -e .
```

The `-e` means “editable”: if you update the source code later, you do not need to reinstall.

**When everything succeeds**, you should see no red `ERROR` lines at the end. Warnings in yellow are usually fine.

### Step 6d — NVIDIA GPU for Uni-pKa (recommended)

`requirements.txt` installs a **CPU** PyTorch wheel so machines without a GPU still work. If you have an NVIDIA GPU, run this in the **same** venv so **Predict pKa**, **Protonate**, and **LogD** use CUDA. The script detects `nvidia-smi` and installs the CUDA 12.4 wheel automatically (~2.5 GB). Pass `-Cpu` / `--cpu` to skip that.

**Windows**

```powershell
.\scripts\install_pytorch_pka.ps1
```

**macOS / Linux**

```bash
bash scripts/install_pytorch_pka.sh
```

Restart MolManager after this step. The guided optional-setup script (`bootstrap_optional_tools`) also runs this automatically.

---

## Part 7 — Start MolManager

Make sure the virtual environment is still active (`(.venv)` in your prompt), then run:

```bash
python -m molmanager
```

The MolManager window should open. Use **File → Open File** to load an SDF, SMILES, or CSV file.

### Starting MolManager later (after you closed the terminal)

Every time you want to use MolManager:

1. Open PowerShell or Terminal.
2. Go to the MolManager folder (`cd` to the project directory).
3. Activate the venv (Part 5).
4. Run `python -m molmanager`.

---

## Optional — Extra setup

Most Python packages are already installed by **Step 6b**. The items below are binaries or data files that are not installed by pip.

### pKa / PyTorch

`pip install -r requirements.txt` installs CPU PyTorch. If you have an NVIDIA GPU, run the script in **Step 6d** (same venv) so Uni-pKa uses CUDA. With no flags it selects CUDA when `nvidia-smi` sees a GPU.

If **Chemistry → Predict → pKa** fails with a PyTorch version error (often after installing another package that upgrades torch), run the same script again to repair the stack. Do **not** create a second environment. Pass `-Cpu` / `--cpu` to force the CPU wheel, or `-Cuda` / `--cuda` to force CUDA. The first **Predict pKa** run downloads Uni-pKa fold weights from Hugging Face (`unipka-download-model`). For offline machines, prefetch with that CLI or copy the fold into unipkainfer’s `model_dir`.

### Docking (Gnina)

Docking is **Protein → Dock Ligand → Gnina…** (file-based CLI with CNN scoring). Receptor PDBQT still comes from **Prepare → Receptor PDB…** then **Prepare → PDBQT…** (Gnina also accepts a PDB receptor). Ligand PDBQT can come from the same PDBQT dialog (Meeko). Python pieces are in the docking extra (`pip install -e ".[docking]"` or `requirements.txt`). Protein Viewer **Render → Interactions** uses ProLIF from that same extra.

The **Gnina** engine is not included in the Python install. Download the official Linux binary from [https://github.com/gnina/gnina](https://github.com/gnina/gnina). On Windows, install it in WSL (Settings → WSL) so `gnina` is on that distro’s PATH. On Linux, either:

- Put `gnina` in:
  - `molmanager/resources/bin/linux/`
- Or set `MOLMANAGER_BUNDLE_DIR` to a folder that contains the executable.

macOS has no official Gnina binary. See **Protein → Dock Ligand** in the app after the binary is reachable.

### Systematic conformers (Open Babel)

**Chemistry → Conformations → Generate → Systematic…** uses Open Babel Confab. Open Babel is a project dependency (`pip install openbabel`, also in `requirements-core.txt`). The dialog defaults to that wheel’s `obabel` (`site-packages/openbabel/bin/obabel`). You can still override the path, or place `obabel.exe` / `obabel` under `molmanager/resources/bin/<platform>/` to prefer a bundled copy.

Distance-geometry ensembles remain **Chemistry → Conformations → Generate → Stochastic…** (RDKit ETKDG; no Open Babel).

### CONFORGE conformers (CDPKit)

**Chemistry → Conformations → Generate → CONFORGE…** uses CONFORGE from [CDPKit](https://cdpkit.org).

On **Windows with Python 3.11**, `pip install cdpkit` (and `pip install -e ".[conforge]"`) will try to compile from source and fail — PyPI has wheels for Windows 3.10/3.12/3.14, not 3.11. Install the CDPKit **MSVC** package from [GitHub Releases](https://github.com/molinfo-vienna/CDPKit/releases), then Browse to `confgen.exe` (usually `C:\Program Files\CDPKit\Bin\confgen.exe`) or add that `Bin` folder to PATH. MolManager also looks in `Program Files\CDPKit\Bin` automatically.

On **Linux/macOS**, `pip install cdpkit` uses a wheel when one exists for your Python version. You can still use a `confgen` binary from PATH, `resources/bin/<platform>/`, or Browse.

### Guided optional setup script

**Windows:**

```powershell
.\scripts\bootstrap_optional_tools.ps1
```

**macOS / Linux:**

```bash
bash scripts/bootstrap_optional_tools.sh
```

This runs `pip install -r requirements.txt`, `pip install -e .`, then `install_pytorch_pka` (CUDA PyTorch when an NVIDIA GPU is present), and can download permeability model weights.

### Permeability model weights

The Chemprop Python packages are in `requirements.txt`, but the **GNN-MTL model file** is not stored in git. Download it once:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

### BioTransformer (Predict Metabolites)

The JAR is **not** in git. Install a JRE so `java` is on `PATH`, then download BioTransformer 3 once:

```bash
python scripts/bootstrap_biotransformer.py
```

That places the official Bitbucket package (`BioTransformer3.0_20230525.jar`, `btkb/`, `supportfiles/`) in `molmanager/resources/models/biotransformer/`. You can also **Browse JAR…** in Predict Metabolites, or set `MOLMANAGER_BIOTRANSFORMER_JAR` (the knowledge-base folder and `supportfiles/` must sit next to the JAR). Manual download: [Bitbucket](https://bitbucket.org/wishartlab/biotransformer3.0jar) / [GitHub](https://github.com/Wishartlab-openscience/Biotransformer). Official docs target UNIX; on Windows try a current JRE, or run the JAR under WSL.

---

## Troubleshooting

### “python is not recognized” (Windows)

Python was not added to PATH. Reinstall Python from python.org and check **Add python.exe to PATH**, or use `py -3.11` instead of `python` in the commands above.

### “cannot be loaded because running scripts is disabled” (Windows PowerShell)

Run once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the venv again.

### NumPy Meson / “Unknown compiler” / `vswhere.exe` (Windows)

Pip is trying to **compile** NumPy from source. That happens when the venv is Python **3.13 or 3.14**: MolManager pins **NumPy 1.x** (PyTorch 2.5 / UMAP), and NumPy 1.26 has no pre-built Windows wheels for 3.13+.

Do **not** install Visual Studio to “fix” this. Recreate the venv with Python 3.11:

1. Check the version: `python --version` (or `py -0p` to list installs).
2. Install [Python 3.11](https://www.python.org/downloads/release/python-3119/) if needed (check **Add python.exe to PATH**).
3. From the MolManager folder, delete `.venv`, then:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-core.txt
pip install -e .
```

### RDKit or NumPy errors (`_ARRAY_API`, import failures)

MolManager needs the official **`rdkit`** package (**2025.9 or newer**), not the obsolete **`rdkit-pypi`** name (last release 2022.9.5). Both install into the same `rdkit` import path, so an old `rdkit-pypi` copy will shadow newer wheels — `import rdkit` then reports 2022.x even if `pip show rdkit` lists 2026.

Use this project's **`.venv`**, not a global conda/base Python that has other chemistry tools. Then:

```bash
pip uninstall rdkit-pypi
pip install -r requirements.txt --force-reinstall
```

MolManager still pins **NumPy 1.x** because PyTorch 2.5 and UMAP/Numba are more reliable on 1.26 than on NumPy 2. That is independent of RDKit (2025.9+ supports NumPy 2).

If wheels still fail on your system, use **conda** for RDKit and pip for the rest:

```bash
conda create -n molmanager python=3.11
conda activate molmanager
conda install -c conda-forge "rdkit>=2025.09.1" pyqt
pip install -r requirements.txt
pip install -e .
```

### PyQtWebEngine fails to install

The app can still run; **Browser** 3Dmol previews may open in your system browser instead of an embedded viewer. On Linux you may need system packages (for example `libegl1` on Debian/Ubuntu).

### “No module named molmanager”

You skipped **Step 6c**. With the venv active, run:

```bash
pip install -e .
```

### pKa / PyTorch conflicts

Use **one** environment only. Run `scripts\install_pytorch_pka.ps1` or `bash scripts/install_pytorch_pka.sh` in the same venv where MolManager is installed (CUDA is selected automatically when `nvidia-smi` sees a GPU). Do not install **admet-ai** in that environment.

### Apple Silicon (M1/M2/M3 Mac)

Core MolManager runs natively. If pKa fails on Apple Silicon, run `bash scripts/install_pytorch_pka.sh` to reinstall the CPU PyTorch stack from `requirements.txt`.

---

## Quick reference (experienced users)

```bash
# One-time setup (from repo root)
python -m venv .venv
# Windows:  .\.venv\Scripts\Activate.ps1
# macOS/Linux:  source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .

# NVIDIA GPU: Uni-pKa CUDA wheel (auto if nvidia-smi sees a GPU)
# Windows:  scripts\install_pytorch_pka.ps1
# Unix:     bash scripts/install_pytorch_pka.sh

# Run
python -m molmanager

# Repair pKa / PyTorch conflicts (same venv; same scripts as above)

# Tests (pytest is already in requirements.txt)
# Windows:  set QT_QPA_PLATFORM=offscreen
# Unix:     export QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -v
```

Editable install extras in `pyproject.toml` (`pka`, `permeability`, `docking`, `conforge`, `dev`) mirror subsets of `requirements.txt` for `pip install -e ".[extra]"` workflows. Prefer `requirements-core.txt` when you only need the table desktop app.

Packaging and installer builds: `docs/PACKAGING.md`.

---

## Configuration (environment variables)

Optional settings for power users and IT deployments:

| Variable | Purpose |
|----------|---------|
| `MOLMANAGER_LOG_LEVEL` | Console log level: `DEBUG`, `INFO`, `WARNING`, … (default `INFO`) |
| `MOLMANAGER_MAX_THREADPOOL` | Main background thread pool size (`1`–`64`; default scales with CPU, cap `16`) |
| `MOLMANAGER_RENDER_THREADPOOL` | 2D structure render pool (`1`–`32`) |
| `MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS` | Row count for async substructure filtering (default `400`) |
| `MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_ROWS` / `MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_MS` | Debounce when a substructure filter is active |
| `MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_ROWS` / `MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_MS` | Debounce for other filters |
| `MOLMANAGER_INGEST_GUI_CHUNK` | File-ingest table insert batch size (default `512`) |
| `MOLMANAGER_SESSION_GUI_CHUNK` | Session restore table insert batch size (default `4096`) |
| `MOLMANAGER_PERF_METRICS` | Enable performance metric logging |
| `MOLMANAGER_PERF_LOG_EVERY` | Perf log interval (default `25` samples) |
| `MOLMANAGER_PLOT_SCATTERGL_MIN_POINTS` | Upgrade marker scatters to WebGL above this count (default `2000`) |
| `MOLMANAGER_PLOT_SELECTION_OVERLAY_MAX` | Max points for SVG/3D selection overlay; larger sets use selectedpoints / skip 3D overlay (default `400`) |
| `MOLMANAGER_CONFORMER_THREADS` | Parallel workers for conformer generation (`1`–`16`) |
| `MOLMANAGER_DESCRIPTOR_THREADS` | Parallel workers for descriptors (`1`–`32`) |
| `MOLMANAGER_PROTOMER_PROCESSES` | Parallel processes for Protonate and Generate Protomers (`1`–`8`) |
| `MOLMANAGER_PKA_GPU` | Set to `0` / `cpu` to force Uni-pKa onto CPU even with a CUDA PyTorch wheel |
| `MOLMANAGER_SQL_MAX_ROWS_HARD` | Hard cap for SQL load row count (default `2000000`) |
| `MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_ROWS` | Hard cap for Diverse Subset pool size (default `200000`) |
| `MOLMANAGER_DIVERSE_SUBSET_EXACT_MAX_ROWS` | Auto mode uses Exact MaxMin at or below this size (default `50000`) |
| `MOLMANAGER_DIVERSE_SUBSET_FAST_CANDIDATE_CAP` | Fast-mode candidate pool size before MaxMin (default `10000`) |
| `MOLMANAGER_SQL_PRECOUNT_WARN` | Confirm before loading if `COUNT(*)` ≥ this (default `100000`) |
| `MOLMANAGER_SQLITE_TIMEOUT_S` | SQLite connection timeout seconds (default `30`) |
| `MOLMANAGER_PG_CONNECT_TIMEOUT` | PostgreSQL connect timeout seconds (default `30`) |
| `MOLMANAGER_SQLITE_BACKEND_PAGE_SIZE` | SQLite cache page size for filters (default `5000`) |
| `MOLMANAGER_DISABLE_CUSTOM_CALC` | Set to `1` / `true` to disable Tools → Custom Calculator |
| `MOLMANAGER_LOG_DIR` | Directory for rotating `molmanager.log` (platform default under user app data / state) |
| `MOLMANAGER_LOG_TO_FILE` | Set to `0` / `false` to disable file logging (console only) |
| `MOLMANAGER_BUNDLE_DIR` | Folder containing optional `gnina` / `vina` binaries |
| `MOLMANAGER_BIOTRANSFORMER_JAR` | Path to the BioTransformer JAR (`btkb/` or `database/`, and `supportfiles/`, must be siblings of the JAR) |

**Custom calculator:** expressions always use a restricted AST interpreter (`calculator_expressions`). Treat them as trusted input only. `MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL` is retired and ignored if set.

**Legacy env aliases:** `CHEMMANAGER_*` variables are still mapped to `MOLMANAGER_*` when the new name is unset, with a deprecation warning. Prefer `MOLMANAGER_*` only.

**Logs:** MolManager writes a rotating log file (default on) and shows the path in the crash dialog on uncaught exceptions.
**SQL URLs in logs:** at `DEBUG`, connection URLs are logged with credentials redacted.

---

## Project layout

| Path | Role |
|------|------|
| `molmanager/app.py` | Application entry point |
| `molmanager/ui/main_window/` | Main window and feature mixins |
| `molmanager/ui/compound_table_model.py` | Table data model |
| `molmanager/ui/dialogs/` | Tool dialogs |
| `molmanager/workers/` | Background jobs (render, export, cluster, pKa, …) |
| `molmanager/storage/` | SQLite mirror for fast filtering |
| `docs/ARCHITECTURE.md` | How components fit together |
| `docs/STEREO_AND_ISOMERISM.md` | Stereochemistry behavior |
| `docs/VALENCE_BONDS_AND_AROMATICITY.md` | Sketcher bond and valence rules |

---

## Development

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for coding standards, Ruff, GPL headers, and CI expectations.

**Tests** (with venv active; pytest is included in `requirements.txt`):

Windows:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest tests/ -v
```

macOS / Linux:

```bash
export QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -v
```

CI runs lint (Ruff + GPL headers) on Ubuntu, and tests on Ubuntu, macOS, and Windows for pushes and pull requests to `main` and `dev` (see `.github/workflows/ci.yml`). Linux also runs the 100k performance gate and a CRITICAL/HIGH/malware `pip-audit` gate (`scripts/check_dependency_audit.py`).

**Lint / headers:**

```bash
python -m ruff check molmanager tests scripts
python -m ruff format --check molmanager tests scripts
python scripts/check_gpl_headers.py
```

**Performance benchmark:**

```bash
python scripts/benchmark_large_table.py --runs 3 --scales 10000,50000,100000
python scripts/benchmark_pka.py samples/fda_approved_physprops_v2.sdf --limit 32
```

---

## Stereochemistry and structures

MolManager (RDKit + the 2D sketcher) handles **tetrahedral** stereo and **alkene E/Z** from 2D layout. It does not automatically enumerate tautomers or atropisomers. See `docs/STEREO_AND_ISOMERISM.md` and `docs/VALENCE_BONDS_AND_AROMATICITY.md` before changing structure-related code.

---

## License

Copyright (C) 2026 Hunter Picard

MolManager is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

The full license text is in [LICENSE](LICENSE).
