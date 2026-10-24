# Bundled resources

## Static assets (in repository)

- **3Dmol.js** — `molmanager/ui/static/3Dmol-min.js` (offline 3D viewer)
- **Liberation Sans 2.1.5** — `molmanager/resources/fonts/LiberationSans-Regular.ttf` (SIL OFL 1.1, see `fonts/LiberationSans-LICENSE.txt`). Structure atom labels; Arial-metric, per IUPAC GR-0. After replacing it, run `python scripts/build_font_metrics.py`.

## Optional CLI binaries (not in git — place locally or use installer)

molmanager can run these when installed on the system **or** when copied into:

```
molmanager/resources/bin/win/     # Windows: optional obabel.exe / mafft.bat (Gnina runs via WSL)
molmanager/resources/bin/linux/ # Linux
molmanager/resources/bin/mac/   # macOS
```

Override the search directory with environment variable `MOLMANAGER_BUNDLE_DIR`.

| Tool | License / size | Install |
|------|----------------|---------|
| **Gnina** | Apache-2.0; CNN docking | [github.com/gnina/gnina](https://github.com/gnina/gnina) — Linux prebuilt (WSL on Windows). Copy `gnina` into `bin/linux/` or put it on the WSL PATH. |
| **Open Babel (`obabel`)** | GPL; Confab systematic conformers | `pip install openbabel` (project dependency). Systematic defaults to the wheel’s `openbabel/bin/obabel`. Optional: copy `obabel` into `bin/<platform>/` to override. |
| **CONFORGE (`confgen`)** | LGPL; CDPKit knowledge-based conformers | Optional. Windows 3.11: CDPKit MSVC installer from [GitHub Releases](https://github.com/molinfo-vienna/CDPKit/releases), then `Bin\confgen.exe`. Linux/macOS: `pip install cdpkit` when a wheel exists. See **Conformations → Generate → CONFORGE**. |
| **MAFFT** | BSD; Protein → Sequence MSA | Not in git. Linux/macOS: `mafft` from apt/brew/conda. Windows: official all-in-one zip from [mafft.cbrc.jp](https://mafft.cbrc.jp/alignment/software/windows.html) — copy `mafft.bat` **and** the sibling `usr/` tree into `bin/win/` (or a `mafft-win/` folder under it). The Sequence dialog can also Browse the folder. |

Python dependencies (RDKit, PyQt5, PyTorch, unipkainfer, Chemprop, Meeko, pytest) are installed via `pip install -r requirements.txt` and `pip install -e .` — see root **README** and **docs/PACKAGING.md**.

## GNN-MTL permeability model (optional, not in git)

`molmanager/resources/models/gnn_mtl/model.pt` — see `models/gnn_mtl/README.md`. Download:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

## BioTransformer 3 (optional, not in git)

`molmanager/resources/models/biotransformer/` — see `models/biotransformer/README.md`. Download:

```bash
python scripts/bootstrap_biotransformer.py
```

Requires Java on PATH plus the official JAR (`BioTransformer3.0_20230525.jar` or `biotransformer-3.0.0.jar`) with sibling `btkb/` or `database/` and `supportfiles/`. Override the JAR with `MOLMANAGER_BIOTRANSFORMER_JAR`, **Settings → Configure → BioTransformer**, or **Browse JAR…** in Predict Metabolites.
