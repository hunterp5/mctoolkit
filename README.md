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

## External tools

The table, sketcher, RDKit descriptors, and stochastic conformers do not need anything in this section. Each program below is optional. Install the ones for the menus you use, then set **Settings → Configure** and click **Test**. The same steps are in the in-app user manual under **External tools** (Help, or F1).

### How MolManager finds a program

1. A key in the machine policy file, when that key is present. The Configure field is then read-only. Paths are in [Configuration](#configuration-environment-variables) below.
2. The path saved by **Settings → Configure**. **OK** writes it. A blank path clears it. **Test** checks the field and does not save.
3. A built-in search: `molmanager/resources/bin/win`, `linux`, or `mac`, then the directory in `MOLMANAGER_BUNDLE_DIR` when that variable is set, then a program of that name on `PATH`, then the install folders named under each tool.

`MOLMANAGER_TOOL_ALLOWLIST` refuses any program whose name or path is not on the list. `MOLMANAGER_TOOL_DIGESTS` refuses a program whose SHA-256 is not in that file.

| Tool | Used by | Configure page | Policy or environment key |
|------|---------|----------------|---------------------------|
| WSL | Windows host for Gnina and AmberTools | WSL | `MOLMANAGER_TOOL_WSL` |
| AmberTools | GAFF / GAFF2 minimization | AmberTools | `MOLMANAGER_TOOL_AMBER` |
| AiZynthFinder | Chemistry → Retrosynthesis | AiZynthFinder | `MOLMANAGER_TOOL_AIZYNTH_PYTHON`, `MOLMANAGER_TOOL_AIZYNTH_CONFIG` |
| Java | BioTransformer | Java | `MOLMANAGER_TOOL_JAVA` |
| BioTransformer | Chemistry → Predict → Metabolites | BioTransformer | `MOLMANAGER_BIOTRANSFORMER_JAR` (environment variable; checked before the saved path) |
| CONFORGE | Conformations → Generate → CONFORGE | CONFORGE | `MOLMANAGER_TOOL_CONFGEN` |
| Gnina | Protein → Dock Ligand | Gnina | `MOLMANAGER_TOOL_GNINA` |
| MAFFT | Protein → Sequence | MAFFT | `MOLMANAGER_TOOL_MAFFT` |
| Open Babel | Conformations → Generate → Systematic | Open Babel | `MOLMANAGER_TOOL_OBABEL` |
| REINVENT | Chemistry → REINVENT → Sampling and Learning | REINVENT | `MOLMANAGER_TOOL_REINVENT` |
| xtb | Calculate Descriptors → Electronic | xtb | `MOLMANAGER_TOOL_XTB` |

AiZynthFinder and REINVENT must stay in their own conda environments. Installing either into `.venv` breaks MolManager’s NumPy and RDKit pins.

### WSL (Windows)

Gnina and AmberTools are Linux programs. On Windows, MolManager starts them with `wsl.exe`. Linux and macOS skip this page.

1. In an elevated PowerShell, run `wsl --install`, reboot, and finish the Linux account (Ubuntu is the usual default).
2. In that distro, `uname -s` should print `Linux`.
3. In MolManager, open **Settings → Configure → WSL**. The usual path is `C:\Windows\System32\wsl.exe`. **Test** runs `uname -s` and should report `Linux`.

Those tools use a login shell (`bash -lic`). A `conda activate` line in the distro’s `~/.bashrc` is visible. A path exported only in the current terminal is not.

### AmberTools

`antechamber`, `parmchk2`, and `tleap` parameterize ligands for **GAFF** and **GAFF2** minimization. OpenMM, in the MolManager environment, then minimizes in vacuum.

On Linux, or inside WSL on Windows:

```bash
conda install -c conda-forge ambertools
```

Debian and Ubuntu can use the distro package instead:

```bash
sudo apt update && sudo apt install ambertools
```

On Windows, put `conda activate` for that environment in the WSL `~/.bashrc`, or install the apt package so `antechamber` is on the default login `PATH`. macOS uses the conda-forge package natively. There is no Windows executable.

OpenMM stays in the MolManager environment (`pip install "openmm>=8.2,<8.3"`, already in `requirements.txt` and the `docking` extra). OpenMM 8.3 and newer crash the simulation subprocess on Windows. GAFF does not fall back to MMFF when parameterization fails.

**Settings → Configure → AmberTools** accepts the command `antechamber`, the `bin` folder that contains it, or the `antechamber` file. `parmchk2` and `tleap` are taken from that same folder. **Folder…** picks the directory. **Test** runs through WSL on Windows.

### AiZynthFinder

**Chemistry → Retrosynthesis → Search**. Release 4.4.1 needs RDKit 2023.x, so it cannot use MolManager’s interpreter (RDKit 2025.9 or newer).

```bash
conda create -n aizynth python=3.11
conda activate aizynth
python -m pip install aizynthfinder "pyarrow>=19,<26"
download_public_data ~/aizynth-data
```

`download_public_data` writes `config.yml` plus the public USPTO models, templates, and `zinc_stock.hdf5` (about 1.8 GB). Python must be 3.10, 3.11, or 3.12. AiZynthFinder 4.4.1 stays on NumPy 1.26, and PyArrow 26 will not import on that NumPy.

**Settings → Configure → AiZynthFinder:**

- **Python** — that environment’s interpreter, for example `C:\Users\you\miniconda3\envs\aizynth\python.exe` or `~/miniconda3/envs/aizynth/bin/python`. Do not pick `.venv`.
- **config.yml** — the file next to the downloaded models.

**Test** imports `aizynthfinder` and reads the config. `use_remote_models: true`, or a MongoDB stock on a host other than localhost, is refused. The search reads models and the stock from disk.

### Java

BioTransformer needs a JRE. MolManager does not bundle one.

- Windows: a current Temurin (or other) JRE, with `java` on `PATH`, or note the path to `java.exe`.
- Debian / Ubuntu: `sudo apt install default-jre`.
- macOS: `brew install openjdk`.

Confirm with `java -version`. **Settings → Configure → Java** — leave the field blank to use `PATH`, or **Browse…** to `java` / `java.exe`. **Test** runs `java -version`.

### BioTransformer

**Chemistry → Predict → Metabolites**. The JAR is not in git. `supportfiles/` and a knowledge-base folder (`btkb/`, `database/`, or `bkdb/`) must sit next to the JAR.

With the MolManager environment active, from the repository root:

```bash
python scripts/bootstrap_biotransformer.py
```

That places the official Bitbucket package (`BioTransformer3.0_20230525.jar`, `btkb/`, `supportfiles/`) in `molmanager/resources/models/biotransformer/`. **Settings → Configure → BioTransformer → Install…** downloads the same package (about 120 MB). **Browse JAR…** picks a JAR you already have. **Test** checks Java and the sibling folders.

`MOLMANAGER_BIOTRANSFORMER_JAR` is checked before the saved path. `MOLMANAGER_OFFLINE=1` refuses the download. Manual download: [Bitbucket](https://bitbucket.org/wishartlab/biotransformer3.0jar) / [GitHub](https://github.com/Wishartlab-openscience/Biotransformer). Official docs target UNIX. On Windows, try the JRE first; if the JAR fails, use the same folder tree under WSL. Commercial redistribution of these files needs permission from the authors.

### CONFORGE (CDPKit)

**Chemistry → Conformations → Generate → CONFORGE…** uses `confgen` from [CDPKit](https://cdpkit.org).

On **Windows**, including Python 3.11, `pip install cdpkit` compiles from source and fails without Boost. PyPI wheels for Windows are CPython 3.10, 3.12, and 3.14, not 3.11. Install the CDPKit **MSVC** package from [GitHub Releases](https://github.com/molinfo-vienna/CDPKit/releases). `confgen.exe` is usually `C:\Program Files\CDPKit\Bin\confgen.exe`.

On **Linux and macOS**, when a wheel exists for your Python:

```bash
pip install cdpkit
```

`pip install -e ".[conforge]"` is the same package. A `confgen` binary still works without the wheel.

**Settings → Configure → CONFORGE** — set the full path, or leave it blank. A blank field is enough when `confgen` is on `PATH`, a copy is under `resources/bin/<platform>/` or `MOLMANAGER_BUNDLE_DIR`, the CDPKit `Bin` folder is in a default location (`Program Files\CDPKit\Bin`, `%LOCALAPPDATA%\CDPKit\Bin`, `/opt/CDPKit/Bin`, `/usr/local/CDPKit/Bin`, `/Users/Shared/CDPKit/Bin`, or `~/CDPKit/Bin`), or the `CDPL` Python bindings import and no path is set. **Test** reports the executable, or the bindings when no path is set.

### Gnina

**Protein → Dock Ligand → Gnina…** is a file-based CLI with CNN scoring. The engine is not in the Python install. Download the official **Linux** binary from [GitHub Releases](https://github.com/gnina/gnina/releases). There is no macOS build and no native Windows executable.

Inside Linux, or inside WSL on Windows:

```bash
chmod +x gnina
sudo mv gnina /usr/local/bin/gnina
command -v gnina
```

You can instead copy that file to `molmanager/resources/bin/linux/gnina`. On Windows, set **WSL** first. MolManager still launches the binary through WSL.

**Settings → Configure → Gnina:**

- Windows: `gnina` when that command is on the WSL `PATH`, or a Linux path such as `/usr/local/bin/gnina`.
- Linux: a full path, or `gnina` on `PATH`.

**Test** resolves the command and reports the path. GPU scoring needs CUDA 12 and cuDNN 9 user-space libraries in that Linux environment (`libcudnn.so.9`, `libcudart.so.12`, and the cuBLAS family). `nvidia-smi` only shows that the driver is visible. If Gnina exits 127 while loading shared libraries:

```bash
conda create -n gnina-cuda -c nvidia -c conda-forge libcudnn cuda-cudart libcublas libcufft libcusparse libcusolver
```

MolManager prepends matching conda `lib` directories to `LD_LIBRARY_PATH`. If `nvidia-smi` fails entirely, docking adds `--no_gpu`.

Receptor PDBQT still comes from **Prepare → Receptor PDB…** then **Prepare → PDBQT…** (Gnina also accepts a PDB receptor). Ligand PDBQT can come from the same dialog (Meeko). Those Python pieces, and Protein Viewer **Render → Interactions** (ProLIF), are in the docking extra (`pip install -e ".[docking]"` or `requirements.txt`).

### MAFFT

**Protein → Sequence** runs `mafft --auto --amino`.

- Debian / Ubuntu: `sudo apt install mafft`
- macOS: `brew install mafft`
- conda: `conda install -c bioconda mafft`
- Windows: the all-in-one zip from [mafft.cbrc.jp](https://mafft.cbrc.jp/alignment/software/windows.html). Keep `mafft.bat` and the sibling `usr/` folder together. Copy both into `molmanager/resources/bin/win/`, or into one subfolder such as `mafft-win/` under that directory.

**Settings → Configure → MAFFT** accepts `mafft`, `mafft.bat`, or the folder that contains them. **Folder…** picks the directory. A blank field uses `PATH`, then `resources/bin/<platform>/` (one child directory deep, including `usr/bin/mafft`). **Test** reports the file it resolved.

### Open Babel

**Chemistry → Conformations → Generate → Systematic…** uses Open Babel Confab. Stochastic ensembles stay on RDKit ETKDG and do not need Open Babel.

Open Babel is already a project dependency (`openbabel` in `requirements-core.txt` and `requirements.txt`). A blank **Settings → Configure → Open Babel** field uses, in order, a copy under `resources/bin/<platform>/` or `MOLMANAGER_BUNDLE_DIR`, the wheel’s `site-packages/openbabel/bin/obabel`, then `obabel` on `PATH`. Set a full path only to force a specific executable. **Test** reports the file it resolved.

MolManager sets `BABEL_LIBDIR` and `BABEL_DATADIR` from that executable. The pip wheel’s import would otherwise point those variables at folders that do not contain `UFF.prm` on Windows, and Confab then fails.

### REINVENT 4

**Chemistry → REINVENT → Sampling** and **Learning**. REINVENT pins its own NumPy, pandas, and PyTorch, so it cannot share the MolManager environment. **Test** refuses MolManager’s Python.

Processor names below are PyTorch index names: `cpu`, a CUDA tag such as `cu126` when the driver matches, or `mac` on Apple silicon.

```bash
git clone --depth 1 https://github.com/MolecularAI/REINVENT4.git
conda create --name reinvent4 python=3.11
conda activate reinvent4
cd REINVENT4
python install.py cpu
reinvent -V
```

The installer puts `reinvent` on that environment’s `PATH` (`Scripts\reinvent.exe` on Windows, `bin/reinvent` on Linux and macOS).

Public priors are a separate download ([doi:10.5281/zenodo.15641296](https://doi.org/10.5281/zenodo.15641296)). Place them in that install’s `priors` folder. The preset ids MolManager offers are `.reinvent`, `.libinvent`, `.linkinvent`, and `.m2m_similarity`. Those names resolve to files in that folder. A full path to a `.prior` file also works.

**Settings → Configure → REINVENT** — browse to that environment’s `reinvent` command. A blank field uses `reinvent` on the `PATH` MolManager inherited, which is empty unless the environment was already active. Prefer the full path. **Test** runs `reinvent -V`. In the sampling and learning dialogs, **Device** is `cpu` or `cuda:0`. `cuda:0` needs a CUDA install (`python install.py cu126`, or the tag that matches the driver).

### xtb

**Calculate Descriptors → Electronic** writes **HOMO (eV)**, **LUMO (eV)**, and **HOMO-LUMO gap (eV)**. The single point uses the lowest-energy conformer in **confs** when that column exists. A 2D structure is embedded once (ETKDG) and minimized with MMFF94 (UFF fallback) for the single point only. xtb does not reoptimize that geometry.

Install the binary from [GitHub](https://github.com/grimme-lab/xtb) or conda:

```bash
conda install -c conda-forge xtb
```

On Windows, use the release `xtb.exe`. You can copy `xtb` or `xtb.exe` into `molmanager/resources/bin/<platform>/`.

When no binary is configured, MolManager uses the `tblite` package in the MolManager environment (`pip install tblite`). The binary is preferred when both are present.

**Settings → Configure → xtb** — a full path, or blank to use `PATH` and then a bundled copy. **Test** expects a version line from the binary. With the field blank and only `tblite` installed, **Test** reports the Python package.

### Packages in the MolManager environment

These are not Configure pages.

**Uni-pKa / PyTorch.** `requirements.txt` installs a CPU wheel. With an NVIDIA GPU, run **Step 6d** in the same environment so Predict pKa, Protonate, and LogD use CUDA. If pKa later fails with a PyTorch version error, run that script again. Do not create a second environment for it. `-Cpu` / `--cpu` forces the CPU wheel. `-Cuda` / `--cuda` forces CUDA. The first **Predict pKa** run downloads Uni-pKa fold weights (`unipka-download-model`). For an offline machine, prefetch with that CLI or copy the fold into unipkainfer’s `model_dir`. `MOLMANAGER_PKA_GPU=0` forces CPU even with a CUDA wheel.

**Permeability weights.** Chemprop is in `requirements.txt`. The GNN-MTL weights file is not in git:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

Override the file with `MOLMANAGER_GNN_MTL_MODEL`.

**Docking helpers.** Meeko, PDBFixer, PDB2PQR, ProLIF, and OpenMM come from `pip install -e ".[docking]"` or `requirements.txt`.

### Guided setup script

The script installs the Python stack. It does not install Gnina, AmberTools, AiZynthFinder, REINVENT, MAFFT, xtb, or CONFORGE.

**Windows:**

```powershell
.\scripts\bootstrap_optional_tools.ps1
```

**macOS / Linux:**

```bash
bash scripts/bootstrap_optional_tools.sh
```

It runs `pip install -r requirements.txt`, `pip install -e .`, then `install_pytorch_pka` (CUDA PyTorch when `nvidia-smi` sees a GPU), and can download the permeability weights and the BioTransformer package.

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
| `MOLMANAGER_OFFLINE` | Set to `1` / `true` to refuse PubChem, ChEMBL, SureChEMBL, ZINC, vendor lookup, BioTransformer download, and the 3Dmol network script |
| `MOLMANAGER_SQL_WRITES` | Set to `0` / `false` to refuse SQL that modifies a database, even if Read-only is unchecked. A read-only load also sets a server read-only transaction on PostgreSQL and MySQL, and refuses any statement that is not a query |
| `MOLMANAGER_SESSION_PLAINTEXT` | Set to `1` / `true` to save a `.cms` as a plain SQLite file. Unset encrypts the file for this OS user. Plaintext sessions still open |
| `MOLMANAGER_SESSION_KEY_DIR` | Directory for `session.key`. Default is `%LOCALAPPDATA%\MolManager` on Windows (DPAPI), `~/Library/Application Support/MolManager` on macOS, and `~/.local/share/MolManager` on Linux (`0600`) |
| `MOLMANAGER_TOOL_ALLOWLIST` | Comma-separated program names or paths, or a text file of one name per line. Unset allows every external program |
| `MOLMANAGER_TOOL_DIGESTS` | Text file of `sha256` and a program name or path. Unset does not hash programs. A mismatch refuses that launch |
| `MOLMANAGER_LOG_DIR` | Directory for rotating `molmanager.log` (platform default under user app data / state) |
| `MOLMANAGER_LOG_TO_FILE` | Set to `0` / `false` to disable file logging (console only) |
| `MOLMANAGER_BUNDLE_DIR` | Folder containing optional `gnina` / `vina` binaries |
| `MOLMANAGER_BIOTRANSFORMER_JAR` | Path to the BioTransformer JAR (`btkb/` or `database/`, and `supportfiles/`, must be siblings of the JAR) |

`MOLMANAGER_OFFLINE`, `MOLMANAGER_SQL_WRITES`, `MOLMANAGER_SESSION_PLAINTEXT`, `MOLMANAGER_SESSION_KEY_DIR`, `MOLMANAGER_TOOL_ALLOWLIST`, and `MOLMANAGER_TOOL_DIGESTS` can also be written in a machine policy file, one `KEY=value` per line. On Windows that file is `%ProgramData%\MolManager\policy.txt`. On macOS it is `/Library/Application Support/MolManager/policy.txt`. On Linux it is `/etc/molmanager/policy.txt`. A key in that file wins over the process environment and over Settings → Configure. Tool paths use `MOLMANAGER_TOOL_GNINA`, `MOLMANAGER_TOOL_OBABEL`, `MOLMANAGER_TOOL_JAVA`, `MOLMANAGER_TOOL_MAFFT`, `MOLMANAGER_TOOL_XTB`, `MOLMANAGER_TOOL_CONFGEN`, `MOLMANAGER_TOOL_REINVENT`, `MOLMANAGER_TOOL_AMBER`, `MOLMANAGER_TOOL_AIZYNTH_PYTHON`, `MOLMANAGER_TOOL_AIZYNTH_CONFIG`, and `MOLMANAGER_TOOL_WSL`. Lines starting with `#` are comments. If the file is absent, only the environment and Configure dialog are used.

**Custom calculator:** expressions always use a restricted AST interpreter (`calculator_expressions`). Treat them as trusted input only. `MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL` is retired and ignored if set.

**Legacy env aliases:** `CHEMMANAGER_*` variables are still mapped to `MOLMANAGER_*` when the new name is unset, with a deprecation warning. Prefer `MOLMANAGER_*` only.

**Logs:** MolManager writes a rotating log file (default on) and shows the path in the crash dialog on uncaught exceptions. `audit.log` in that same folder records file opens, imports, exports, session saves, SQL hosts, and external-program launches. It stores file names and hosts, not folder paths, SQL passwords, or structures.
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

PyQt5 is used under the GPL. A build that includes that Qt library stays GPL-3. Shipping the same application under a proprietary license would require a commercial Qt license instead. The Linux CI job writes `sbom.cdx.json` for the environment it tested and uploads that file with the run.
