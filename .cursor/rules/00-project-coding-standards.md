## ChemManager / MolManager coding standards

These rules apply to all new or modified code in this repository.

### Copyright headers

- Every **new** source file must include the standard MolManager GPL copyright header (same text as existing `.py` files).
- Keep a shebang as line 1 when present; put the header immediately below it.
- Do not add the header to vendored/third-party assets.
- See `.cursor/rules/copyright-headers.mdc` for the full header text.

### Python style and formatting

- Use **PEP 8** and keep code clean and maintainable.
- Format Python code with **Ruff**.
- Prefer **type hints** for public functions and non-trivial internal helpers.
- Avoid redundant comments; only comment on non-obvious intent or trade-offs.

### Naming conventions

- Use **snake_case** for variables and functions.
- Use **PascalCase** for classes.
- Use descriptive names; avoid single-letter names except for conventional loop indices.

### Quality and correctness

- Fix problems at the **cause**, not at the symptom.
- Keep UI responsive by offloading heavy work off the GUI thread.
- Keep changes cohesive; avoid drive-by refactors unless required.
- Prefer narrow `except` clauses. Do not use `except Exception: pass`.

### Git commits

- When one batch contains more than one functional change, give each file its own commit if a single message would mix unrelated work. See `.cursor/rules/per-file-commits.mdc`.
- Each of those commits uses an imperative subject and a short paragraph on why.
- Files that belong to one change may share a commit. A file that itself mixes two changes still gets one commit, and that message covers both reasons.
- **Never** add `Co-authored-by`, "Coauthored by Cursor", Cursor Agent attribution, or `cursoragent@cursor.com` to commits, PRs, or other project text.

