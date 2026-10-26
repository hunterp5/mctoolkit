# Gnina

Gnina runs the Gnina docking engine (a Smina/Vina fork with CNN scoring) with a receptor PDB or PDBQT, a ligand file, box center/size, and search settings.

## Goal

Dock prepared ligands into a receptor box and collect poses/scores from MolManager, including CNN pose scores when enabled.

## When to use

Use when PDB/PDBQT receptor prep is done and you want local Gnina runs without leaving the app.

Protein Viewer **Tools → Prepare → Fast Prepare…** and **Tools → Prepare → Dock File…** fill the receptor PDBQT and numeric search box (crystal-ligand AABB + padding). The docking **Ligand** field is left empty so you can choose compounds to dock. The crystal ligand extracted by those tools is kept for **internal validation** (on by default).

**Protein → Dock Ligand → Gnina…** and Protein Viewer **Tools → Dock Ligand…** open this dialog. **File → Session → Save Session** stores the paths and options (receptor, ligand, output, box, pharmacophore, flexible residues, CNN settings, and the crystal ligand used for validation). Opening the dialog in that session fills them back in. A running job is not saved.

## Inputs / scope

Requires a **Gnina** command, receptor PDB or PDBQT, ligands, and an output path. Ligands come from a **file** or from **selected table rows** plus a **conformations** column. Box defined by center and size, or **Autobox**.

On **Windows**, Gnina is the official Linux binary and runs through **Settings → Configure → WSL** (same path as AmberTools). Put `gnina` on the WSL PATH, or set a Linux path such as `/usr/local/bin/gnina` under **Settings → Configure → Gnina**. You can also copy the binary to `molmanager/resources/bin/linux/gnina`. GPU CNN scoring uses CUDA inside WSL. `nvidia-smi` in WSL only checks the Windows GPU driver; Gnina also needs Linux **user-space** CUDA 12 and cuDNN 9 libraries (`libcudnn.so.9`, `libcudart.so.12`, …). If Gnina exits 127 with “error while loading shared libraries”, install those libs in WSL, for example:

`conda create -n gnina-cuda -c nvidia -c conda-forge libcudnn cuda-cudart libcublas libcufft libcusparse libcusolver`

MolManager prepends matching conda `lib` dirs to `LD_LIBRARY_PATH`. If `nvidia-smi` fails entirely, MolManager adds `--no_gpu`. macOS has no official Gnina binary.

## Options

- **Receptor**, **Ligand**, **Output** (+ **Browse...**). The Gnina binary is **Settings → Configure → Gnina** (WSL PATH name `gnina` on Windows). Receptor may be **PDB or PDBQT**. If the receptor file still contains a ligand, Gnina docks into an **apo** copy. **Ligand** is **File** (SDF; Browse also lists MOL/MOL2; PDBQT is converted to SDF) or **Selected rows**. Selected rows docks each selected table row once; **Conformations** chooses the packed ensemble column (`confs`, `superpose`, …) or **Structure** for the starting 3D geometry (first packed conformer). Gnina then samples poses itself — the rest of the ensemble is not docked as extra ligands. **Save as SDF** (on by default) sets Gnina `--out` to SDF. Uncheck it only if you need PDBQT poses (that format cannot store double/aromatic bonds). Concatenated Meeko PDBQT is converted to one multi-mol SDF and docked in a **single** Gnina process. If Ligand is empty and **Internal validation** is on with a crystal ligand available, Run redocks the crystal ligand only.
- **Pharmacophore** - optional MolManager pharmacophore JSON from **Protein Viewer → Tools → Pharmacophore → Editor** (**Save…**, or **Send to Gnina**). Gnina itself is unchanged (no occupancy `--user_grid`; that flag *scales Vina down* when λ is set and is type-blind). After poses are written, MolManager keeps those whose RDKit feature sites of the matching type (and element, when **Atom** is set) lie inside each query sphere in **protein coordinates**. **Slack** (default 0.50 Å) is extra tolerance on top of each feature radius. **Exclusion** spheres drop a pose if a ligand heavy atom is inside (that element when **Atom** is set). If nothing matches, all poses are kept and the log says so. Pose properties `pharmaMatch`, `pharmaRMSD`, and `pharmaN` are written for the browser.
- **Autobox** - Gnina `--autobox_ligand` plus **Padding** (`--autobox_add`, default 4 Å). Optional **Browse…** next to the checkbox sets a reference ligand (**PDB or PDBQT**); empty uses the docking ligand. Disables center/size.
- **Flexible side chains** - **Off** (default, rigid receptor), **Distance from ligand**, or **Named residues**. Backbone stays rigid. Distance mode uses `--flexdist` / `--flexdist_ligand` (default 3.5 Å; empty ligand field uses the Autobox / Prepare crystal ligand, then the docking ligand). **Max** (`--flex_max`) keeps only the closest N residues (0 / all keeps every residue in range). Named residues are `CHAIN:RESNUM` (`A:123,A:145`). Gnina writes moved side chains to `{output stem}_flex.pdb` (`--out_flex`). **Write full receptor** adds `--full_flex_output`. The pose browser still overlays the ligand in the original pocket; open the flex PDB to inspect side chains.
- **Center X/Y/Z** and **Size X/Y/Z** - search box when autobox is off.
- **Exhaustiveness**, **Num modes**, **CPU threads**.
- **CNN** - `rescore` (default), `none` (empirical Vina/Vinardo only), or `refinement` (slower). Optional built-in model (`dense`, `fast`, `crossdock_default2018`) and pose sort (`CNNscore`, `CNNaffinity`, `Energy`).
- **Use GPU** - CUDA when available; uncheck to force `--no_gpu`.
- **Internal validation** - on by default. When a crystal ligand is available (still in the receptor file, or the Dock File / Fast Prepare sidecar), redock it with the same box and search settings. The log and pose-browser title report **crystal RMSD** (Å, heavy atoms, no superposition) of the top-ranked validation pose versus the crystallographic coordinates. **crystalRMSD** and **crystalRef** (the ligand residue or file used as that reference) are written only on that redocked crystal-ligand entry, not on other docked ligands. Uncheck to skip the extra run.
- **Minimize Docked Poses** - after docking, run `gnina --minimize` on all poses in one process. The SDF/PDBQT include both the **placement** pose and the **minimized** pose (`poseStage`).
- Pose output also includes vacuum **E_MMFF** and **E_UFF** (kcal/mol) for each ligand pose so you can see how strained the geometry is. These are not protein-bound ΔG.
- **Working dir**, **Extra args**.
- **Run Gnina** / **Stop** / **Close**. **Run Gnina** closes this window immediately; progress and Gnina stdout go to the **Protein Viewer** log. **Stop** remains on this dialog if you reopen it, and on **Processes**.

## Workflow

1. On Windows, confirm **Settings → Configure → WSL** and that `gnina` works in that distro (`command -v gnina`), or set the binary under **Settings → Configure → Gnina**. On Linux, set the Gnina path if it is not on PATH. Download the prebuilt binary from [github.com/gnina/gnina/releases](https://github.com/gnina/gnina/releases) if it is missing.
2. Choose receptor, ligands (**File** or **Selected rows** + **Conformations**), and output paths.
3. Define the box (center/size, or **Autobox**) and search / CNN parameters.
4. **Run Gnina**. The docking window closes; watch the **Protein Viewer** log for launch lines and Gnina output. **Stop** from **Processes** (or reopen **Gnina…**). When the run finishes, poses are packed into a **poses** column on the matching table rows (or new rows for file-docked ligands), and they open in the **pose browser**, docked in the Protein Viewer **Manager** when that window is open (full Manager column; **header arrows** switch to the chain list; **Undock** for a floating window). If Protein Viewer is not open, the pose browser floats on its own. If **poses** already exists, a new run writes **poses (1)** (then **poses (2)**, …) so earlier ensembles are kept. The table lists every pose for the current ligand (**Pose** id, then `CNNscore`, `CNNaffinity`, affinity, **E_MMFF**, **E_UFF**, RMSD, **crystalRef**, mode, and other Gnina fields when present; SMILES is omitted); click a row to show that pose. **E_MMFF** / **E_UFF** are vacuum single-point ligand energies (kcal/mol), not protein-bound ΔG. **← / →** (or Home / End) switch among docked ligands when more than one structure was docked. The 3D pane shows the **ligand pose only**; if **Protein → Viewer** is open, the same pose is also drawn in that pocket **with the crystal ligand still visible** (docked pose carbons are magenta). **Pose Browser Settings** can **Add pose to Viewer** or **Add all poses to Viewer** so they appear as Manager structures beside the crystal complex. Closing the pose browser removes that overlay. **Pose Browser Settings** (gear) also controls ligand drawing style and **Save poses**. The SDF (or PDBQT) is also written to the output path. **Protein → Dock Ligand → Pose Browser** brings the pane back if you closed it, including after **File → Session → Open Session** (the last run is stored with the packed **poses** column).

## Use cases

- Redock a crystallographic ligand to validate the box (**Internal validation**, on by default when a crystal ligand is present).
- Sample pocket side chains (**Flexible side chains → Distance from ligand** or **Named residues**) when induced fit is expected.
- Dock a small selected series with higher exhaustiveness.
- Compare empirical Vina/Vinardo (`CNN: None`) with default CNN rescoring.

## Tips and limits

Right-click a packed **poses** cell and choose **View Poses** to open that row's poses in the Protein Viewer pocket. The receptor and crystal-ligand paths from the run are kept with the column, including after **File → Session → Open Session**. If the receptor file has moved, the poses still open and the missing pocket is reported.

Docking quality hinges on box placement and ligand/receptor prep. Prefer an SDF ligand; PDBQT stores AutoDock types, not Kekulé orders. Covalent docking and custom CNN `.pt` models are Extra-args only in this dialog. Flexible side chains are in the **Flexible side chains** section (not Extra). Long CNN refinement jobs occupy the GPU - prefer **Rescore** for screening. Prebuilt Gnina is Linux/WSL; do not expect a native Windows `.exe`.
