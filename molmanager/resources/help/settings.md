# Settings

Settings control appearance, keyboard shortcuts, and paths for optional external tools: themes, application/table fonts, the hotkey editor, whether the status bar is shown, and **Configure** (WSL, Gnina, BioTransformer, and the other tools that need a local install).

## Goal

Make MolManager readable and efficient for your display and preferred shortcuts without changing chemistry results.

## When to use

Adjust when switching light/dark preference, changing monitor DPI, or customizing shortcuts for frequent tools.

## Inputs / scope

Global UI preferences for this installation/session; they do not alter table chemistry data.

## Options

- **GUI**
  - **Theme** - **Light Mode** / **Dark Mode** / **Groovy Mode**, plus named custom themes.
  - **Custom Colors...** (under **Theme**) - edit named custom themes (palette roles, save/delete).
  - **2D Render...** - pixel size of 2D structure drawings in the Structure column.
  - **Font...** - **Application font size**, **Table font size**, **Table text alignment** (3×3: top/center/bottom × left/center/right), **Reset to Default**.
- **Hotkeys...** - category/command/shortcut table with OK/Cancel, **Clear Selected**, and **Reset to Default**.
- **Status Bar** - show or hide the bottom bar (status messages and memory use).
- **Configure** - paths for optional external programs. Each page has **Browse...**, **Test**, and **OK**.
  - **WSL...** - path to ``wsl.exe`` so Windows can run Linux-only tools (Gnina, AmberTools / GAFF, and similar). **Test** runs ``uname -s`` inside WSL.
  - **AmberTools...** - ``antechamber`` command, bin folder, or executable. ``parmchk2`` and ``tleap`` are taken from the same folder. On Windows the command runs in WSL.
  - **BioTransformer...** - JAR for Predict Metabolites (**Browse JAR...** / **Install...**). ``supportfiles/`` and ``btkb/`` (or ``database/``) must sit next to the JAR.
  - **CONFORGE...** - CDPKit ``confgen`` executable.
  - **Gnina...** - docking binary. On Windows this is the Linux command used through WSL (``gnina`` or a path such as ``/usr/local/bin/gnina``).
  - **Java...** - ``java`` for BioTransformer. Blank uses ``java`` on PATH.
  - **MAFFT...** - executable or install folder for Protein → Sequence.
  - **Open Babel...** - ``obabel`` for systematic conformers.

## Workflow

1. Open **Settings → GUI → Theme** and pick a theme or **Custom Colors...**.
2. Open **Settings → GUI → Font** and set font sizes so the table and dialogs stay readable.
3. Edit hotkeys for commands you use often; reset if a binding conflicts.
4. Open **Configure** and set **WSL...** plus any tool path (Gnina, BioTransformer, AmberTools, and the others) you will run.
5. Confirm changes and return to the table.

## Use cases

- Dark theme for long evening analysis sessions.
- Larger table font for dense numeric columns.
- Bind a hotkey to Filters or Plotter for rapid iteration.

## Tips and limits

Theme and font changes are visual only. Hotkey conflicts can leave a command unreachable until cleared or reset. Custom themes are saved by name - delete unused ones to keep the list short.
