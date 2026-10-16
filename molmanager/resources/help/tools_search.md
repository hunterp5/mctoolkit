# Search

Search builds multi-criterion queries across columns with AND/OR/NOT logic, optional partial/case options, and SMARTS/substructure mode for structure columns.

## Goal

Find rows matching one or more textual or structural criteria quickly, then select or inspect the matches.

## When to use

Use for ad-hoc lookup (ID, name fragment, SMARTS) when a standing filter card is unnecessary.

## Inputs / scope

Searches the current table columns. Structure criteria need a valid structure/SMARTS-capable column.

## Options

- Criterion rows with **AND** / **OR** / **NOT** combinators.
- **Column** chooser and query field.
- **Partial match** and **Case Sensitive** options.
- **Substructure** / SMARTS mode for structure search.
- **Add** / **−** on every criterion row. **−** on the last remaining row deletes that search and closes Search.
- Closing Search from the menu or shortcut hides the panel but keeps query rows until they are deleted.

## Workflow

1. Open **Search** and set the first column + query.
2. Add more criteria with **AND**, **OR**, or **NOT** as required. **NOT** removes rows that match that criterion from the matches so far.
3. Enable **Substructure** when querying with SMARTS.
4. Jump to or select matches, then optionally promote logic into Filters.

## Use cases

- Find all rows whose ID contains a lot prefix.
- OR across synonym name columns.
- SMARTS-search a reactive motif before MMP analysis.

## Tips and limits

AND/OR/NOT mixes follow the criterion list order - keep queries simple when unsure. Invalid SMARTS yield no matches. Search is complementary to Filters; use Filters for persistent constraints. An open Search panel and its active query rows are stored in the session file and restored on Open. Toggling Search off keeps the current queries; use **−** to delete a row, or the last **−** to clear Search and close the panel.
