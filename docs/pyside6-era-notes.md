# Notes from the PySide6 era (2026-09-19 to 2026-09-21)

Written when reverting `main` to the last PyQt5 commit because Qt 6 / PySide6
left the desktop app unusable (black Chromium boxes, window blink on load,
plot resize glitches, selection lag, launch flashes).

This file is the inventory of work to **re-apply later on PyQt5**, not a
history of the broken tree. Do **not** port the Qt 6 WebEngine workarounds.

## Git landmarks

| What | Commit | Date |
|---|---|---|
| Last PyQt5 tree (restore target) | `13a4e9c` | Sat Sep 19 14:50 CDT |
| PySide6 + combined Processes window | `3972edb` | Sat Sep 19 15:49 CDT |
| Package rename molmanager → mctoolkit | `5f86ab2` | Sun Sep 20 |
| `.mct` sessions, Mol* viewer, MD analysis | `541b5ac` | Sun Sep 20 |
| ADME + Uni-pKa install; save/builds off UI | `3ff62ed` | Sun Sep 20 |
| HEAD at revert time | `b6a75f2` | Mon Sep 21 21:55 CDT |

- **157 commits** sit on `13a4e9c..b6a75f2` (also on `origin/main` and `origin/dev`).
- Backup branch of that HEAD: **`archive/pyside6-era`**.
- Uncommitted session-load / Render 2D pool work was stashed as
  `pyside6-era uncommitted WIP` (see `git stash list`).
- Remote was **not** force-pushed. `origin/main` still has the PySide6 history.

Last PyQt5 package layout:

- Python package: `molmanager/`
- Sessions: `.cms` (not `.mct`)
- Qt: `PyQt5>=5.15` + `PyQtWebEngine>=5.15`

Restore locally (already done if you are reading this on the reverted tree):

```text
git branch archive/pyside6-era b6a75f2   # keep the old HEAD
git reset --hard 13a4e9c
```

Inspect old code without switching:

```text
git show 3972edb:molmanager/ui/processes_dialog.py
git log --oneline 13a4e9c..archive/pyside6-era
```

---

## Do not port back

These were Qt 6 HWND / Chromium compositing band-aids. They caused most of
the quality drop. Re-implement features **without** them.

- `WA_DontCreateNativeAncestors` / native-island `WebSurface` / QQuickView detours
- Floating every Plotly / Mol* / 3Dmol / sketcher window with `parent=None`
- Unmapping Chromium during splitter drag, freeze-covers, `ForceHostResize`
- Opaque white Chromium clear color, Fusion Window fill behind WebEngine
- Skipping `winId()` to avoid nativizing the workspace
- Layout freeze / hide / reparent during session restore
- Launch WebEngine prewarm (and the later “skip prewarm” counter-fix)
- Host-resize throttle / compositor kicks / canvas stretch in the Plotly shell

On PyQt5, `QWebEngineView` was a child widget. Keep that model.

---

## Features to re-implement on PyQt5

Priority is user-visible product work, then architecture that helps it.

### 1. Combined Log window (shipped in `3972edb`, later renamed)

User request: one corner button for jobs + transcript.

- In-memory session log (`platform_support/session_log.py`) fed by app logging
- Modeless window: job table on top, filterable log below (level, search,
  autoscroll, copy, clear, open file)
- Later rename: corner button and window title **Log** (not Processes)
- Keep the button enabled during ingest so a long load can be watched
- Log filters on the same footer row as job buttons (protein-viewer chat)

Chats: [System-wide log button](dbd9e88e-6a0a-44ce-8780-02cfcf73128b),
[ROSHAMBO searching](d773008c-0b9d-468a-9f34-37023aad741d),
[Menu and dialog restoration](de7d7a3b-8928-4594-9100-a0037010b745).

### 2. Per-job progress (do not steal rows)

User request: a new tool’s description must not overwrite a running job.

- Progress stored **per job id**, not one global string
- `enqueue(..., job_id=)` / begin-first helpers; finish/clear by id or label
- Overlay jobs (Render 2D, Gnina) append; they do not jump to row 0
- Wire the same id through descriptors, Fast Prepare, protonate, conformers,
  fragments, calculator writeback, reaction enum, QSAR, pharmacophore, PDBQT,
  PDBFixer, FP/bulk similarity, diverse subset, medchem, dimred, filters,
  SQL load, SQLite rebuild, tautomer/protomer

Chats: [Custom colors dialog update](1d627136-a8b9-4819-aed9-9fb1aa98c3d5),
[Tool progress logging issue](9292b49c-6eed-444f-af1f-07e8418b599b),
[Restore Lost Changes](6ec8cd39-caa3-48db-a63d-3f297bd844fb).

### 3. Menu, hotkeys, dialog polish

- Data → Table → **Operations** (Add Row/Column, Split, Join)
- **Ctrl+O / Ctrl+S** → Open/Save Session (not file import/export)
- **Status Bar** under Settings (not GUI)
- Dialog chrome: Reset on the same row as OK/Cancel; theme name + Reset on
  the custom-theme action row; clip/seed/scope checkboxes on the same rows
  as their fields; compact 2D render size fields; drop the hotkeys hint
- Plot pane close **X** centered in its button

Chat: [Menu and dialog restoration](de7d7a3b-8928-4594-9100-a0037010b745),
[Plot close X](d31f44dd-6f8a-4b1c-833c-d2ae9edab428).

### 4. Status bar completeness

- Invert Selection, Select All, empty-cell, first-occurrence: `Selected N of M`
- Sort / rename / filter-panel show-hide
- Protomer / tautomer results copied to the main bar
- Predict pKa: **per-molecule** ticks (do not change scoring; GPU chunks of
  8/16 still apply). Cancelled rows write `Cancelled.` and retry as uncalculated
  (`rescore_oids`, drop cache). Placeholder `Error` cells count as fillable

Chats: [Status bar update issues](fbe63ec8-81fe-42f0-aa84-24b4317e9c8c),
[PKA predictor status updates](4536c5d0-cf97-428a-bd3c-c98be50420df).

### 5. Chemistry / product features that landed after PyQt5

Re-apply these as new work on the PyQt5 tree. Source is on `archive/pyside6-era`.

| Feature | Landmark commit | Notes |
|---|---|---|
| Tautomer enumeration + browser | `f57a1dc` | Cap ~8 forms; Parent OID / score / canonical |
| Protein MD + MM/GBSA | `f57a1dc` | Bundled binaries stay gitignored |
| Mol* protein viewer | `541b5ac` | Keep QWebEngineView as a normal child on PyQt5 |
| Native `.mct` sessions | `541b5ac` | Zip + SQLite; still load old `.cms` |
| Local ADME prediction | `3ff62ed` | Bootstrap models; do not pull ADMET-AI / conflicting torch |
| Uni-pKa model install | `3ff62ed` | Same env as existing pKa path |
| Session save / table builds / Chemprop off the GUI thread | `3ff62ed` | Keep this; it is not a WebEngine hack |
| Reuse cancelled tool columns | `375b4a8` | Error/Cancelled/N/A cells are fillable |
| GUI theme in the session | `375b4a8` / `9370141` | Restore Dark/Light/custom with Open |
| External under Tools | `15f6950` | Menu regroup |
| Split/Join one bulk update; wheel stays on focused control | `3b15ec8` | |
| Hide owned Windows console under pythonw | `6f6dbf8` | `gui-scripts` entry `524973a` |
| Search-panel children parented (no orphan HWND flash) | `434c4d4` | Real launch-window bug, keep the parenting fix |

### 6. Table / plot responsiveness (the good parts only)

- Giant rubber-band selections: promote to OID highlights after settle;
  do not restyle every live plot on every mouse move
- Skip table→plot echo restyles when the click originated in the plot
- Structure paint must **not** mark SQLite/session dirty; lazy 2D decode on
  scroll must **not** emit `dataChanged` for the whole visible column
- Keep the table in Qt’s backing store (do not promote it to a native HWND)

Chats: [App responsiveness issues](4611e70b-719f-43f1-be95-0917053dcdaf),
[Table scrolling responsiveness](ee018312-3e73-49ea-8a74-426beddda3f3).

### 7. Session Open overlay (careful)

User wanted: one loading surface until rows, filters, plots, and 2D are ready;
no window that opens, closes, then opens again.

A covering overlay + off-thread parse **is** wanted. The PySide6
implementation fought Chromium and blinked. On PyQt5:

- Parse session bytes off the GUI thread
- Show a simple in-widget overlay (not a native `QWindow` stacked over
  Chromium)
- Reveal once; do not hide/show the main window
- Persist 2D PNGs in the session or a sidecar cache so Open does not
  re-render every structure (uncommitted `session_structure_cache.py` /
  `render2d_mp.py` on the stash)

Chat: [Session loading optimization plan](350a67cd-50aa-4f1b-9198-12949b50df9d),
[Smooth Session Loading](81238ead-56f6-41df-9e4a-f91decf0eb1c).

### 8. Architecture that is worth keeping (without Qt 6)

Landed in the same era, mostly independently of WebEngine:

- Sketch chemistry moved out of the sketcher widgets into `chem/`
  (`acs_sketch_style`, `sketch_mol`, …) — **this was in `3972edb`**
- `TableWriteService` + `TableCellReader` (dialogs must not call
  `app._table_cell_text`)
- Drop `bind_mixin_methods`; window MRO is the shell; tools live on
  collaborators (`WorkspaceTools`, `TableSession`, `SessionController`,
  `TableBuildPipeline`)
- Display name **MCtoolkit** / package **mctoolkit** (rename was `5f86ab2`;
  the reverted tree is still `molmanager`)
- Cursor rules: one commit per file, layering, new-feature wiring,
  qt-threading, tests, module-shape, python-data-and-structure
- Architecture ratchet may only go **down**

Chats: [Mixins usage discussion](a04b244c-dece-40f1-8a45-c24eff0d7164),
[Architecture Step Plan](319020d3-8174-4569-85ba-211d26cd750f),
[Rename Project](634875d4-4e6f-4133-be35-992c97950e98),
[Python style](ec9237dd-2c27-49e2-a06a-722f03ac27b8).

---

## Open feature requests (not fully shipped, or ideas)

Revisit these on the PyQt5 tree. Do not require PySide6.

### Medicinal chemistry (from [Medicinal chemistry app ideas](eeada3fc-b53e-4a81-8d6f-a6256f5a1887))

- Ligand efficiency suite: LE, LLE, SILE, BEI, SEI, Fit Quality from
  activity + HAC / LogD
- Structural alerts: PAINS, Brenk, NIH, Dundee, SureChEMBL + SMARTS highlight
- R-group SAR matrix (R1 × R2 heatmap of pIC50, Free-Wilson / MMP additive)
- Selectivity indices from two or more assay columns
- Bioisostere / MMP analog generator (“what should I make next?”)
- Soft-spot blocking from BioTransformer metabolites, scored with MPO
- Shape / 3D similarity (USRCAT / RDKit shape; ROSHAMBO chat)
- Purchasable analog search (Enamine REAL / ZINC / Mcule)
- Dock-time tautomer + unspecified-stereo expansion (cap ~16 forms/parent),
  write poses back onto Parent OID — **not** a main-table explode

### Platform / UX still requested

- Prevent Windows sleep while a job runs (`SetThreadExecutionState`);
  lid-close / Start-menu Sleep cannot be blocked
  ([Dialog box scrolling behavior](8bd847df-3027-4072-96bc-e67fcc44b079))
- Close fire-and-forget dialogs on Run (Diverse Subset, FP Similarity,
  Cluster) while the job continues in Log
- Protein Viewer Invert Selection is still a stub
- Protein queue jobs (Fast Prepare, Minimize, PDBFixer, pdb2pqr, MD,
  MM/GBSA, Gnina file dock) still do not call main-window tool progress
- Chemprop GNN-MTL follow-ups without pulling ADMET-AI torch
  ([Chemprop Tools](6555db2e-f2de-49f7-88f3-893687a93f8d),
  [ADME Prediction](9c0f5d4d-4394-45f6-90a7-ad0f1fefdf67))

### Problems that were never actually fixed on PySide6

Treat these as **regression tests** when anything Qt-ish is touched later:

- Plot / splitter resize: black box or blink-then-rerender
- Session Open: overlay progress, then the window appears to close, flash
  white, and resume
- App launch: a window opens, closes, then the real window appears
  (orphan search-panel widgets as top-level HWNDs was one cause)
- Selecting thousands of plot points stalls further selection
- Table scroll hitch from Structure `dataChanged` + lost backing store

---

## Uncommitted work at revert time

Working tree on `b6a75f2` had in-progress **smooth session load** changes
(not in `archive/pyside6-era` until the stash):

Modified (session restore, plots, Render 2D, theme, progress, benchmarks,
tests): `app.py`, `qt_webengine_flags.py`, `structure_render_store.py`,
`structure_depiction_layout.py`, `docked_plot_session.py`,
`chemistry_workspace_window.py`, `plot_pane.py`, `table_ui_mixin.py`,
`workspace_layout.py`, `mol_3d_html.py`, `plot_session_mixin.py`,
`plotly_shell.html`, `progress_controller.py`, `session_controller.py`,
`session_plots.py`, `session_restore.py`, `session_save.py`,
`table_build_layout.py`, `table_build_render.py`,
`table_build_render_results.py`, `theme.py`, `workers/load_render.py`,
plus matching tests and `README.md`.

New modules (stash these; they are the interesting bits):

- `mctoolkit/chem/render2d_mp.py`
- `mctoolkit/storage/session_structure_cache.py`
- `mctoolkit/ui/session_load_progress.py`
- `mctoolkit/workers/render2d_pool.py`
- `mctoolkit/workers/render2d_subprocess.py`
- `tests/test_session_load_smooth.py`

Scratch `_tmp_*` probes, drag screenshots, and `samples/chembl_37.sdf`
were left untracked on disk and were **not** committed.

---

## Chat index (post-transition)

Use these if you need the original request wording.

| Chat | Id | What was asked |
|---|---|---|
| ROSHAMBO searching | `d773008c-0b9d-468a-9f34-37023aad741d` | PySide6 port + combined Processes |
| System-wide log button | `dbd9e88e-6a0a-44ce-8780-02cfcf73128b` | Log next to Processes, then merge |
| Mixins / architecture | `a04b244c-dece-40f1-8a45-c24eff0d7164` | Collaborators, drop bind_mixin_methods |
| Architecture Step Plan | `319020d3-8174-4569-85ba-211d26cd750f` | Window MRO = shell |
| Rename Project | `634875d4-4e6f-4133-be35-992c97950e98` | mctoolkit |
| ADME Prediction | `9c0f5d4d-4394-45f6-90a7-ad0f1fefdf67` | Local ADME |
| Chemprop Tools | `6555db2e-f2de-49f7-88f3-893687a93f8d` | GNN-MTL without ADMET-AI |
| Mol* | `c6c08bb1-6e19-4f3f-ad84-c8d6522e7655` | Protein viewer |
| Medicinal chemistry ideas | `eeada3fc-b53e-4a81-8d6f-a6256f5a1887` | LE/LLE, alerts, SAR matrix, … |
| Custom colors / menus | `1d627136-a8b9-4819-aed9-9fb1aa98c3d5` | Theme + job-id progress diagnosis |
| Session load plan | `350a67cd-50aa-4f1b-9198-12949b50df9d` | Overlay until ready |
| pKa status | `4536c5d0-cf97-428a-bd3c-c98be50420df` | Per-molecule bar |
| Status bar ops | `fbe63ec8-81fe-42f0-aa84-24b4317e9c8c` | Invert / sort / rename |
| Python style rules | `ec9237dd-2c27-49e2-a06a-722f03ac27b8` | Cursor `.mdc` split |
| Table scrolling | `ee018312-3e73-49ea-8a74-426beddda3f3` | Scroll hitch |
| Plot close X | `d31f44dd-6f8a-4b1c-833c-d2ae9edab428` | Center the glyph |
| Per-file commits | `243c8413-7ee3-4330-9756-588c888d7ba1` | git-commits.mdc |
| Restore Lost Changes | `6ec8cd39-caa3-48db-a63d-3f297bd844fb` | Re-apply non-WebEngine work |
| Menu restoration | `de7d7a3b-8928-4594-9100-a0037010b745` | Operations, Ctrl+O/S, Log |
| App responsiveness | `4611e70b-719f-43f1-be95-0917053dcdaf` | Plot selection lag |
| Plot resize glitch | `1024cbd1-31a5-4648-b3a4-8cb6ea7224d7` | Live splitter look |
| Smooth Session Loading | `81238ead-56f6-41df-9e4a-f91decf0eb1c` | Fast Open, no blink |
| Launch window flash | `f246c80f-96c3-4b4f-b7f6-9e8f5dcdef12` | One window at start |
| Black box investigation | `6e7a13b0-3d51-4550-974e-b57f5d4dc7dc` | Qt 6 HWND vs PyQt5 |
| QWebEngine timeline | `20e98af5-441f-404d-a9ee-e6ed47a8804c` | When it broke (`3972edb`) |

---

## Appendix: commits `13a4e9c..b6a75f2`

157 commits. Themes, newest first, as of `b6a75f2`:

- Merge `dev` into `main`
- Structure paint / lazy scroll not dirty
- Large selection OID promotion + plot sync
- Named job ids through every tool
- Live splitter (later dropped freeze-covers)
- Menu: Operations, Log, Ctrl+O/S, Status Bar on Settings, dialog polish
- Session Open overlay, off-thread parse, theme restore
- Chromium isolation / black-box workarounds (skip when porting)
- Windows console hide, `gui-scripts`
- Compact FDA fixtures
- Coding-standards `.mdc` split, one-commit-per-file rule
- ADME, Uni-pKa, save/builds off UI, cancelled-column reuse
- mctoolkit rename, `.mct`, Mol*, MD analysis, tautomer
- Collaborator split, External under Tools, MCtoolkit identity
- **`3972edb` PySide6 + Processes/Log + sketch chem + TableWriteService**
