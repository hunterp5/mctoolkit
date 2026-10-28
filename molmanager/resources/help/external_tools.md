# External tools

Optional programs that MolManager does not ship. The table, sketcher, descriptors, and RDKit conformers work without any of them. Install only the tools for the menus you use, then point **Settings → Configure** at each one and click **Test**.

## Goal

Get a local install of each optional program, and save the path MolManager will launch.

## When to use

After the Python install in the project README, and again when **Test** on a Configure page says the program was not found.

## How a path is chosen

MolManager looks in this order:

1. A line in the machine policy file, when that key is present. The Configure field is then read-only. On Windows the file is `%ProgramData%\MolManager\policy.txt`. On macOS it is `/Library/Application Support/MolManager/policy.txt`. On Linux it is `/etc/molmanager/policy.txt`. One `KEY=value` per line. `#` starts a comment.
2. The path saved by **Settings → Configure** (**OK** writes it; a blank path clears it).
3. A built-in search: `molmanager/resources/bin/win`, `linux`, or `mac`, then `MOLMANAGER_BUNDLE_DIR` when that variable is set, then a program of the same name on `PATH`, then a few well-known install folders named under each tool below.

**Test** checks the path in the field and does not save it. **OK** saves it. A policy key wins over both.

If `MOLMANAGER_TOOL_ALLOWLIST` is set, the program name or path must be on that list or the launch is refused. `MOLMANAGER_TOOL_DIGESTS` refuses a program whose SHA-256 is not in that file.

| Tool | Menu | Configure page | Policy key |
|------|------|----------------|------------|
| WSL | Windows host for Gnina and AmberTools | WSL | `MOLMANAGER_TOOL_WSL` |
| AmberTools | GAFF minimization | AmberTools | `MOLMANAGER_TOOL_AMBER` |
| AiZynthFinder | Chemistry → Reaction → Retrosynthesis | AiZynthFinder | `MOLMANAGER_TOOL_AIZYNTH_PYTHON`, `MOLMANAGER_TOOL_AIZYNTH_CONFIG` |
| BioTransformer | Chemistry → Predict → Metabolites | BioTransformer | `MOLMANAGER_BIOTRANSFORMER_JAR` (environment variable) |
| Java | BioTransformer | Java | `MOLMANAGER_TOOL_JAVA` |
| CONFORGE | Conformations → Generate → CONFORGE | CONFORGE | `MOLMANAGER_TOOL_CONFGEN` |
| Gnina | Protein → Dock Ligand | Gnina | `MOLMANAGER_TOOL_GNINA` |
| MAFFT | Protein → Sequence | MAFFT | `MOLMANAGER_TOOL_MAFFT` |
| Open Babel | Conformations → Generate → Systematic | Open Babel | `MOLMANAGER_TOOL_OBABEL` |

## WSL

Windows only. Gnina and AmberTools are Linux programs. MolManager starts them with `wsl.exe`. Linux and macOS do not use this page.

### Install

1. In an elevated PowerShell, run `wsl --install`.
2. Reboot when Windows asks, and finish the Linux user account in the new distro (Ubuntu is the usual default).
3. Open the distro and confirm `uname -s` prints `Linux`.

### Configure

**Settings → Configure → WSL**. The usual path is `C:\Windows\System32\wsl.exe`. Leave the field as MolManager fills it when `wsl` is already on `PATH`. **Browse…** picks another `wsl.exe`. **Test** runs `uname -s` inside WSL and should report `Linux`.

Gnina and AmberTools use a login shell (`bash -lic`), so a `conda activate` line in that distro's `~/.bashrc` is visible. A path set only in the current terminal is not.

## AmberTools

`antechamber`, `parmchk2`, and `tleap`. Chemistry → Conformations → Generate uses them for **GAFF** and **GAFF2** minimization. OpenMM in the MolManager environment then minimizes the parameterized ligand in vacuum.

### Install

On Linux, or inside the WSL distro on Windows:

```bash
conda install -c conda-forge ambertools
```

Debian and Ubuntu can use the distro package instead:

```bash
sudo apt update && sudo apt install ambertools
```

On Windows, put `conda activate` for that environment in the WSL `~/.bashrc`, or install the apt package so `antechamber` is on the default login `PATH`. macOS uses the same conda-forge package natively. There is no Windows `.exe`.

OpenMM stays in the MolManager environment, not in the AmberTools environment:

```bash
pip install "openmm>=8.2,<8.3"
```

`requirements.txt` and `pip install -e ".[docking]"` already install that pin. OpenMM 8.3 and newer crash the simulation subprocess on Windows. There is no fallback to MMFF when GAFF parameterization fails.

### Configure

**Settings → Configure → AmberTools**. The field may be the command `antechamber`, the `bin` folder that contains it, or the `antechamber` file itself. `parmchk2` and `tleap` are taken from that same folder. **Folder…** picks the `bin` directory. **Test** checks that `antechamber` can be executed (through WSL on Windows).

## AiZynthFinder

Local retrosynthesis for **Chemistry → Reaction → Retrosynthesis → Search**. It cannot share MolManager's environment: release 4.4.1 needs RDKit 2023.x, and MolManager uses RDKit 2025.9 or newer.

### Install

```bash
conda create -n aizynth python=3.11
conda activate aizynth
python -m pip install aizynthfinder "pyarrow>=19,<26"
python scripts/bootstrap_aizynth_data.py ~/aizynth-data
```

`bootstrap_aizynth_data.py` writes `config.yml` plus the public USPTO ONNX models, templates, and `zinc_stock.hdf5` from Zenodo (about 1.5 GB). **Settings → Configure → AiZynthFinder → Download…** does the same thing. AiZynthFinder's `download_public_data` fetches the ZINC stock from a Figshare link that expires after 10 seconds, so the stock download fails and `config.yml` is never written. AiZynthFinder 4.4.1 stays on NumPy 1.26. PyArrow 26 will not import on that NumPy, which is why the pin is `<26`. Python must be 3.10, 3.11, or 3.12.

### Configure

**Settings → Configure → AiZynthFinder** has two fields:

- **Python** — `python.exe` (Windows) or `python` from the `aizynth` environment. A typical Windows path is `C:\Users\you\miniconda3\envs\aizynth\python.exe`. A typical Linux path is `~/miniconda3/envs/aizynth/bin/python`. Do not pick MolManager's `.venv` interpreter.
- **config.yml** — the file written next to the model files.

**Test** imports `aizynthfinder` in that interpreter and reads the config. A config with `use_remote_models: true`, or a MongoDB stock on a host other than localhost, is refused. The search reads the model and stock files from disk.

## Java

The runtime for BioTransformer. MolManager does not bundle a JRE.

### Install

Install a current Temurin or distro JRE and confirm `java -version` works.

- Windows: the Eclipse Temurin installer, with **Add to PATH** checked, or note the path to `java.exe` (often under `C:\Program Files\Eclipse Adoptium\`).
- Debian / Ubuntu: `sudo apt install default-jre`.
- macOS: `brew install openjdk`.

### Configure

**Settings → Configure → Java**. Leave the field blank to use `java` on `PATH`. **Browse…** picks `java.exe` or `java`. **Test** runs `java -version`.

## BioTransformer

Local metabolite prediction for **Chemistry → Predict → Metabolites**. The JAR is not in git. `supportfiles/` and a knowledge-base folder (`btkb/`, `database/`, or `bkdb/`) must sit next to the JAR.

### Install

With the MolManager environment active, from the repository root:

```bash
python scripts/bootstrap_biotransformer.py
```

That downloads the official Bitbucket package into `molmanager/resources/models/biotransformer/` (`BioTransformer3.0_20230525.jar`, `btkb/`, `supportfiles/`). The same download is **Settings → Configure → BioTransformer → Install…** (about 120 MB). Java must already be installed.

Manual download: [Bitbucket](https://bitbucket.org/wishartlab/biotransformer3.0jar). Official docs target UNIX. On Windows, try the JRE first. If the JAR fails, install the same folder tree under WSL and point the path at that JAR.

### Configure

**Settings → Configure → BioTransformer**. **Browse JAR…** picks the JAR. **Test** checks Java and that `supportfiles/` and a knowledge-base folder are siblings of the JAR.

`MOLMANAGER_BIOTRANSFORMER_JAR` is an environment variable, checked before the saved Configure path. The sibling folders still have to sit next to that JAR. `MOLMANAGER_OFFLINE=1` refuses the **Install…** download.

Commercial redistribution of the BioTransformer files needs permission from the authors.

## CONFORGE

CDPKit `confgen`, for **Chemistry → Conformations → Generate → CONFORGE**.

### Install

**Windows, including Python 3.11.** PyPI has no `cdpkit` wheel for Windows CPython 3.11, so `pip install cdpkit` tries to compile and fails without Boost. Download the CDPKit **MSVC** installer from [GitHub Releases](https://github.com/molinfo-vienna/CDPKit/releases) and run it. The executable is usually `C:\Program Files\CDPKit\Bin\confgen.exe`.

**Linux and macOS.** In the MolManager environment, when a wheel exists for your Python:

```bash
pip install cdpkit
```

`pip install -e ".[conforge]"` is the same package. You can still install the CDPKit `Bin` tree and use `confgen` without the Python wheel.

### Configure

**Settings → Configure → CONFORGE**. Set the full path to `confgen` or `confgen.exe`, or leave the field blank when any of these is true:

- `confgen` is on `PATH`
- a copy is in `molmanager/resources/bin/<platform>/` or `MOLMANAGER_BUNDLE_DIR`
- the CDPKit `Bin` folder is in a default location: `Program Files\CDPKit\Bin`, `%LOCALAPPDATA%\CDPKit\Bin`, `/opt/CDPKit/Bin`, `/usr/local/CDPKit/Bin`, `/Users/Shared/CDPKit/Bin`, or `~/CDPKit/Bin`
- the `CDPL` Python bindings import (`ConfGen.ConformerGenerator`) and the field is blank

**Test** reports the executable it resolved, or the Python bindings when no path is set.

## Gnina

CNN docking for **Protein → Dock Ligand → Gnina**. The official build is a Linux binary. There is no macOS build and no native Windows `.exe`.

### Install

Download the Linux binary from [GitHub Releases](https://github.com/gnina/gnina/releases). Inside Linux, or inside WSL on Windows:

```bash
chmod +x gnina
sudo mv gnina /usr/local/bin/gnina
command -v gnina
```

You can instead copy that file to `molmanager/resources/bin/linux/gnina`. On Windows, MolManager still launches it through WSL. Set **WSL** first.

GPU scoring needs CUDA 12 and cuDNN 9 user-space libraries inside the same Linux environment (`libcudnn.so.9`, `libcudart.so.12`, and the cuBLAS family). `nvidia-smi` only shows that the driver is visible. If Gnina exits 127 with “error while loading shared libraries”, install the libraries in WSL or Linux:

```bash
conda create -n gnina-cuda -c nvidia -c conda-forge libcudnn cuda-cudart libcublas libcufft libcusparse libcusolver
```

MolManager prepends matching conda `lib` directories to `LD_LIBRARY_PATH`. If `nvidia-smi` fails entirely, docking adds `--no_gpu`.

Receptor PDBQT still comes from **Protein → Prepare**. Ligand PDBQT can be written with Meeko from the docking extra (`pip install -e ".[docking]"` or `requirements.txt`).

### Configure

**Settings → Configure → Gnina**.

- **Windows:** `gnina` when that command is on the WSL `PATH`, or a Linux path such as `/usr/local/bin/gnina`. A Windows path to a file you copied is converted to `/mnt/…` and must still be a Linux ELF.
- **Linux:** a full path, or `gnina` on `PATH`.

**Test** resolves the command (inside WSL on Windows) and reports the path it found.

## MAFFT

Multiple-sequence alignment for **Protein → Sequence** (`mafft --auto --amino`).

### Install

- Debian / Ubuntu: `sudo apt install mafft`
- macOS: `brew install mafft`
- conda: `conda install -c bioconda mafft`
- Windows: the all-in-one zip from [mafft.cbrc.jp](https://mafft.cbrc.jp/alignment/software/windows.html). Keep `mafft.bat` and the sibling `usr/` folder together. Copy both into `molmanager/resources/bin/win/` (or a single subfolder such as `mafft-win/` under that directory).

### Configure

**Settings → Configure → MAFFT**. The field may be `mafft`, `mafft.bat`, or the folder that contains them. **Folder…** picks an install directory. A blank field uses `PATH`, then `resources/bin/<platform>/` (one child directory deep, and `usr/bin/mafft` inside that tree). **Test** reports the file it resolved.

## Open Babel

`obabel` for **Chemistry → Conformations → Generate → Systematic** (Confab). Stochastic conformers use RDKit and do not need Open Babel.

### Install

Open Babel is a project dependency. It is installed by `pip install -r requirements-core.txt` and by `requirements.txt` (`openbabel`). Confirm the wheel's program exists. In the MolManager environment:

```bash
python -c "import openbabel, pathlib; print(pathlib.Path(openbabel.__file__).parent / 'bin')"
```

A separate system install is optional. If you use one, keep its format plugins next to the executable. MolManager sets `BABEL_LIBDIR` and `BABEL_DATADIR` from the executable it launches. The pip wheel's own import would otherwise point those variables at folders that do not contain `UFF.prm` on Windows, and Confab then fails.

### Configure

**Settings → Configure → Open Babel**. Leave the field blank to use, in order, a copy under `resources/bin/<platform>/` or `MOLMANAGER_BUNDLE_DIR`, the pip wheel's `openbabel/bin/obabel`, then `obabel` on `PATH`. Set a full path only when you want a specific executable. **Test** reports the file it resolved.

## Packages in the MolManager environment

These are not Configure pages. They install into the same virtual environment as MolManager.

- **Uni-pKa** (Predict pKa, Protonate, LogD) needs PyTorch. `requirements.txt` installs a CPU wheel. With an NVIDIA GPU, run `scripts\install_pytorch_pka.ps1` or `bash scripts/install_pytorch_pka.sh` in that environment. The script selects the CUDA 12.4 wheel when `nvidia-smi` sees a GPU. The first pKa run downloads fold weights (`unipkainfer`). `MOLMANAGER_PKA_GPU=0` forces CPU.
- **Permeability** needs the Chemprop packages from `requirements.txt` and a weights file that is not in git: `python scripts/bootstrap_gnn_mtl_model.py`. Override the file with `MOLMANAGER_GNN_MTL_MODEL`.
- **Docking helpers** (Meeko, PDBFixer, PDB2PQR, ProLIF, OpenMM) come from `pip install -e ".[docking]"` or `requirements.txt`.

`scripts\bootstrap_optional_tools.ps1` and `scripts/bootstrap_optional_tools.sh` install `requirements.txt`, the editable package, the PyTorch step, and can download the permeability weights and the BioTransformer package. They do not install Gnina, AmberTools, AiZynthFinder, MAFFT, or CONFORGE.

## Tips and limits

Install AiZynthFinder in its own conda environment. Installing it into `.venv` breaks MolManager's NumPy and RDKit pins. On Windows, confirm **WSL** before **Gnina** or **AmberTools**. **Test** on each Configure page is the check that the path is the one MolManager will launch.
