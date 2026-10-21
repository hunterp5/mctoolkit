# Import Data

Import Data appends or merges external rows/columns into the current table instead of starting from a blank session.

## Goal

Enrich the open library with additional structures or property columns while keeping existing work in place.

## When to use

Use when combining assay exports, adding a second supplier file, or merging computed results from another tool.

## Inputs / scope

Current table plus an external file. Matching/merge behavior depends on the import path and shared identifiers or append mode.

## Options

- **Source file** - choose the external file to bring in. The file is added to **File → Open Recent**. Choosing it there later opens it with **Open File**, which replaces the current table.
- **Append / merge** - combine into the active session table rather than replacing the session wholesale.
- **New columns / rows** - appear in the main table after import completes.

## Workflow

1. Open or create the destination session.
2. Run **Import Data** and choose the file.
3. Verify row counts and new columns.
4. Resolve duplicates or empty structures before modeling.

## Use cases

- Append a follow-up assay plate to an existing project session.
- Merge computed descriptors exported from another pipeline.
- Add a small focused set of analogs into a larger deck.

## Tips and limits

Column name collisions can overwrite or require renaming after import. Structure validity is still required for chemistry tools. Prefer Sessions for full project snapshots rather than repeated ad-hoc imports. A loading page stays up until imported rows are merged and filter bounds are ready; auto **Render 2D** continues in the background (skipped when the row count is over the auto-2D limit).
