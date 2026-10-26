# Find and Replace

Find and Replace edits text in editable table cells. One undo restores the whole edit.

## Goal

Replace text, a wildcard pattern, or cells that pass a comparison, then step through the matches or apply the change everywhere in scope.

## When to use

Use when the same substitution belongs in many cells. Use Search (Ctrl+F) when you only want to select matching rows, or when the query needs AND, OR, or SMARTS.

## Inputs / scope

- **Find** and **Replace**. Find has to contain text. An empty replacement deletes the matched text.
- `*` matches any sequence and `?` matches one character. They are wildcards in Find only. The replacement is written as typed, including `*` and backslashes.
- A find text that starts with `>`, `>=`, `<`, `<=`, `=`, `!=`, or `<>` compares the whole cell. `>10` and `>= -2` are numeric. `=ethanol` matches that whole cell as text, and `=10` also matches `10.0`. A bare `10` stays a literal substring. `>abc` matches nothing.
- `empty`, `blank`, `is:empty`, and `is:blank` match a blank cell. `not empty`, `!empty`, `notempty`, `is:notempty`, `is:notblank`, and `not blank` match a cell that has text. Use `=empty` or `*empty*` to find the word.
- **Column** is one editable text column, or all of them. ID, Structure, and image columns are skipped.
- **Scope** is visible rows (the default), the entire table (including rows hidden by filters), or the selected cells.
- **Match case** requires the same letter case for text and wildcards. Off still inserts the replacement as typed. Numeric comparisons ignore case.
- **Whole cell** replaces the cell only when its entire value matches. Off replaces every matching span. Comparisons always replace the whole cell.

## Options

- **Find Next** selects the next matching cell and wraps after the last one.
- **Replace** rewrites the current match, or the next match when the current cell does not match, then moves on.
- **Replace All** counts the hits, asks before writing, and stores every changed cell in one undo step.
- Closing the bar keeps the text. A new session clears it.

## Workflow

1. Open **Edit → Find and Replace…** (Ctrl+H), or choose **Find and Replace…** on a column header.
2. Enter the find text and the replacement. Choose the column and scope.
3. Use **Find Next** to inspect matches, **Replace** to edit one cell, or **Replace All** to edit every match in scope.
4. Use **Edit → Undo** to restore every cell from that replace.

## Use cases

- Rename a lot prefix in an ID column.
- Clear a placeholder token from notes with `TODO*`.
- Replace every potency above 5 with a label.

## Tips and limits

AND, OR, and SMARTS stay in Search. Cells whose text would not change are skipped. Replacing text in a SMILES column changes that cell's text only; the Structure column stays as it is. Rows can leave the view when a filter no longer matches the new text. An open bar and its fields are stored in the session file and restored on Open.
