# Click-by-click macro recording

The macro tool that ships now is an explicit recipe. The user adds steps, fills in parameters, and runs them. It does not watch the screen. Recording clicks is a different architecture, and the current window cannot support it without a command layer underneath the menus.

This document is the plan for that layer. The recipe runner should move onto it rather than grow a second set of one-shot callbacks.

## What recording has to capture

A useful recording is not a list of `QAction` clicks. A click on Calculate Descriptors only opens a dialog. The thing worth replaying is the accepted request: which descriptors, which structure column, which rows, and which column headers came back.

Each recorded step needs:

- A stable command id (`chemistry.descriptors`, `tools.calculator`, `table.filter.apply`, …).
- The parameters the user committed, as plain data, not widget state.
- The row scope at accept time (all rows, the selection, or the visible set), stored as a scope name rather than a snapshot of object ids. Object ids from the recording session will not match the table the user replays onto.
- The outputs the command published (internal key → header that was actually written), so the next recorded step can keep a `${step.key}` reference instead of a uniquified title like `MolWt (1)`.
- How the command finishes: synchronous, process-queue job, background job, or "this dialog does not run a job".

Intermediate widget edits (typing in a spin box, checking a box, then cancelling the dialog) are not steps. The step is the accept.

## Why the current code cannot record

Menus are a tree of slot names in `ui/main_window/menu_spec.py`. A slot opens a dialog. The dialog reads its own widgets and calls a window method. Parameters are not a value the menu can see.

Completion is also per tool, not per job:

- Descriptors and several other calculations share `WorkerSignals.calculated`, then `on_calc_finished`. A macro waits by stashing `_macro_descriptor_done` on the window. The next `calculated` signal consumes it. A second tool that finishes first would complete the wrong step.
- The calculator waits on `_calculator_on_done`. Protonate waits on `_protonate_on_done`. Reaction enumeration waits on `_macro_reaction_done`. Filters wait on `_macro_filter_done`.
- `on_calc_finished` may return before the cells exist. Large writes finish later, in `on_complete`. A recorder that listens to the worker signal records the step too early, and the next step reads columns that are not there yet.
- Output headers are uniquified inside `on_calc_finished` (`MolWt` becomes `MolWt (1)` when the column is already filled). The name the user typed is not the name the next step must use.
- `AppKernel` is the whole window. `docs/ARCHITECTURE.md` says new workflows must not take it. A recorder that calls window methods directly would cement that coupling.

`ProcessQueueManager.thread_finished` is also the wrong signal. It fires when the worker thread returns, which is before chunked table writeback finishes.

## Target shape

Four pieces, none of which import each other in the wrong direction.

### 1. Command catalog

A Qt-free module, next to `workflows/macro_recipe.py`, lists every recordable command:

- id, user-facing label, and which menu it corresponds to
- a parameter schema (required fields, types, row-scope flag)
- the output keys the command publishes (`MolWt`, `output`, `percent`, `pka`, or none)
- the completion kind: `sync`, `process_queue`, `background`, `none`

The recipe document already is a subset of this catalog (`descriptors`, `calculator`, `protonate`, `filter`, `reaction`). Recording should append the same step objects the editor writes today, not a second format.

### 2. Request objects

Dialogs become editors of a request dataclass. Accept builds the request and hands it to one function. The dialog does not call `_enqueue_column_calc` or read `src_combo` from a mixin.

Several tools already have this shape and should be the pattern:

- `ReactionEnumerationRequest`, `RGroupEnumerationRequest`
- `ProtomerGeneratorRequest`, `PotencyRequest`, `DiverseSubsetRequest`
- `ProteinPrepareRequest`, `BiotransformerRequest`

These still build the request inside the dialog and then branch in the mixin. Recording only needs the request to be the value that crosses into the runner.

These do not have a request object yet. The recipe runner reached around them with `start_*` methods. Those methods are the interim dispatch. The dialog and the recorder should both call them with a request, and the widget-reading code should move into `dialog.request()`:

- Calculate Descriptors (`PropertyDialog.get_selected()` plus the structure combo)
- Calculator (column name, expression, scope)
- Protonate (`ProtonateDialog.config()` is still a tuple)
- Filter cards (the session document already serializes cards; a macro clause is a smaller version of that)

`CalcDescriptorsRequest` exists on the worker, but it is built after the dialog has already pulled molecules out of the table. The recorded request should be the user's choices (source, keys, scope), not the hydrated molecule payloads. Payloads are captured at replay time.

### 3. One dispatch function

```text
dispatch(host, command_id, params) -> JobHandle
```

`host` is a narrow protocol: table headers, row count, selection, visible oids, enqueue, and "write these columns and call me when the cells exist". It is not `AppKernel`.

`JobHandle` has:

- `job_id` shared with the process queue and the progress slot
- `finished(outcome)` where outcome is `{ok, error, cancelled, outputs: {key: header}}`
- `cancel()`

The recipe runner, the menu, and the recorder all call `dispatch`. The recorder does not connect to `QAction.triggered`.

The handle's `finished` fires from the same place `on_complete` fires today, after chunked writeback, not from the worker thread and not from `thread_finished`. Filter handles fire from `_finalize_filter_apply` (every path already ends there, including SQLite and chunked apply). Reaction handles fire from `on_reaction_enum_finished` / `on_reaction_enum_failed` after rows are inserted.

Synchronous commands (add a filter card with no async apply, rename a column) complete before `dispatch` returns. The handle is already finished.

### 4. Recorder states

The recorder is a small object on the window with three states.

**Idle.** `dispatch` runs the command and nothing is stored.

**Recording.** `dispatch` runs the command as usual. On `finished`, if `ok` and not `cancelled`, append a recipe step whose params are the request and whose id is allocated the same way as `new_step_id`. If the command's outputs include uniquified headers, store the binding on the step so the next recorded command can rewrite a column it just consumed into `${thisStep.key}` when the user picks that column in the next dialog. If the user cancels the dialog, `dispatch` is never called, so nothing is appended.

**Replaying.** The recipe runner calls `dispatch` with the stored params. Dialogs do not open. The recorder ignores these calls so a replay is not recorded again.

Recording starts and stops from Tools → Macros, as actions on the same library. A recording in progress is a recipe that is still being appended. Stop leaves it in the library for editing before Run.

## Column identity

This is the part that makes a recording replayable on a different table.

At record time the descriptor command asks for `MolWt` and the table write names the column `Mol Weight` or `Mol Weight (1)`. The recorded step stores the key `MolWt`, not the header. Replay calls the same command. The new table may name the column `Mol Weight (2)`. The binding is updated from that run's outcome.

When a later recorded step used that column, the recorder rewrites the stored parameter if the user picked the column this session just created. The stored text becomes `${desc1.MolWt}` rather than `Mol Weight (1)`. The recipe runner already resolves those references in `substitute_column_refs`. Replay does not need a new substitution language.

Calculator expressions are the awkward case. The worker matches bare names and `[bracketed names]`. A uniquified header is not a Python identifier. The runner already wraps those in brackets when substituting. The recorder should insert `${step.key}` into the expression, not the raw header, when the chosen column is an output of an earlier recorded step.

Row scope is a name (`table`, `selection`, `visible`), which the recipe already stores. Do not record the object ids that were selected. On replay, "selected rows" means whatever is selected then. "Visible rows" means whatever the filters from earlier steps are showing.

## What stays unrecorded

Do not install an event filter on `QApplication` to capture mouse and key events. That records dialog noise, plot camera moves, sketcher atom drags, and protein-viewer clicks, and it cannot see the parameters of a modal dialog that was cancelled.

Leave these out until each one has a command:

- PCA, medchem space, and docked views other than the plotter. Plotter settings (axes, color, spokes, limits) are a step. Zoom and pan are not.
- Sketcher edits
- Protein viewer, protein prepare, Gnina, and minimizations
- Table scrolling, column resize, and theme changes
- Selection drags, until `table.select_rows` exists as a command. Until then, a recording that depends on a selection uses the Selected rows scope and the user selects before replay.

Copy, paste, add column, split, join, and bin are good later commands because they already end in `on_calc_finished` or a direct table edit. They are not in the first recipe on purpose. Add them to the catalog one at a time, each with a request object and a `JobHandle`, and the recorder picks them up without a new recording mechanism.

## Migration order

The recipe runner is the client that proves the gateway. Replace its private callbacks as each command moves over. Do not build the recorder until the five current steps go through `dispatch` and a test can replay a recipe without opening a dialog.

1. **JobHandle and dispatch for the five recipe steps.** The runner now calls `dispatch_step` and waits on a `JobHandle` (`ui/command_dispatch.py`, `ui/job_handle.py`). The catalog is `workflows/command_catalog.py`. The five tools still finish by writing `_macro_descriptor_done`, `_calculator_on_done`, `_protonate_on_done`, `_macro_reaction_done`, or `_macro_filter_done`; deleting those slots is the per-job completion step below. Dialogs still call `start_*` directly.
2. **Request objects for descriptors, calculator, protonate, and filter clauses.** Done in `workflows/tool_requests.py`. The dialogs expose `request()`, and dispatch builds the same objects from a saved step. `get_selected()` remains for the descriptor checklist tests. Per-job completion is still the one-shot callbacks.
3. **Per-job completion inside writeback.** Each descriptor, calculator, protonate, and reaction job now has its own signal object (`ui/job_signals.py`). The finish slot closes over that job's callback and column context, and `on_calc_finished(..., on_complete=)` still runs after the cells exist. A second queued job cannot overwrite the first job's callback. Filter applies use `FilterWait`, and a newer apply fails the previous wait. The recorder is the next step.
4. **Recorder on top of dispatch.** `MacroRecorder` appends a step only from `JobHandle.finished` when the job succeeded. Tools → Macros → Record starts it. Accepting Calculate Descriptors, Calculator, Protonate, or Reaction Enumeration appends that request. A header written earlier in the recording is stored as `${stepId.key}`. Run sets the replaying flag so playback is not recorded again. Widening the catalog is the next step.
5. **Widen the catalog.** Random number, reaction extract, plotter settings, potency, R-group enumeration, explicit hydrogens, neutralize, and fast prepare are commands. Table tools finish from `on_calc_finished(..., on_complete=)`. Structure tools use a signal object per job and complete after the structures are written; Render 2D keeps drawing in the background. Plot settings are the plotter session state. Zoom and pan are not stored. Tools → Macros → Add plot snapshots the open plotter. Selection as its own command, and undo grouping, are the remaining plan items.
6. **Selection and filter edits as commands**, if recordings need "select these rows" rather than "use whatever is selected at replay". That is a product choice. The scope flag covers the common case without it.
7. **Undo grouping**, later and optional. Tool writeback does not push `QUndoCommand`s today. A recorded run is a series of the same writes. Grouping them into one undo is independent of recording and should not block it.

## Tests that define "done"

Without a window:

- The catalog's ids and output keys round-trip through `macro_recipe`.
- `dispatch` is not imported by `workflows/` (no Qt).

With a window, or a fake host that records calls:

- Accepting descriptors while recording appends one step and no step when the dialog is cancelled.
- Two overlapping descriptor jobs resolve to the job id that was started, not whichever `calculated` signal arrives.
- A replay of descriptors then calculator substitutes the header from the first job's outcome into the expression, including a uniquified name.
- Cancelling the running job does not append a step and does not start the next recorded step.

## What not to do

- Do not record `QEvent`s, mouse paths, or screenshots.
- Do not point the recorder at `AppKernel`.
- Do not add more `_macro_*_done` attributes for new tools. New tools get a `JobHandle`.
- Do not store object ids, pixmap bytes, or hydrated RDKit molecules in the recipe. Store the user's choices. Read the table at replay time.
