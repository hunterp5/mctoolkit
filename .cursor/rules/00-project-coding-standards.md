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

- Anytime a git commit is made, write **detailed messages for every file that was altered** (brief per-file bullets).
- **Never** add `Co-authored-by`, "Coauthored by Cursor", Cursor Agent attribution, or `cursoragent@cursor.com` to commits, PRs, or other project text.

