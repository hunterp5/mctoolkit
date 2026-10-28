# Protein Sequence

Protein → Sequence aligns amino-acid sequences with a local **MAFFT** install. It is a separate workspace from the Protein Viewer Sequence window.

## Goal

Build a named sequence pool from FASTA, pasted text, or polymer chains in an open Protein Viewer, run MAFFT (`--auto --amino`), and inspect or export the alignment.

## When to use

Use **Protein → Sequence…** when you want a Clustal-style multiple-sequence alignment. Use **Protein → Viewer → Sequence** when you want to inspect or right-click **Mutate** residues on a loaded 3D structure.

## Inputs / scope

Does not read or write the compound table.

- **Open FASTA…** — multi-record FASTA (`.fa`, `.fasta`, `.faa`).
- **Paste FASTA / sequences…** — FASTA headers, or bare amino-acid strings separated by blank lines.
- **Add from Protein Viewer** — polymer chains from the open Viewer. Uppercase and lowercase letters become the same amino acid; Viewer hetero tokens `+` / `*` / `~` are dropped.

You need at least two sequences to Align. MAFFT install and path setup are in **External tools**.

## Options

- **Rename** / **Remove** — edit the pool (double-click a row to rename).
- **Align** — run MAFFT. **Cancel** stops a long job. The executable is **Settings → Configure → MAFFT** (a file or the all-in-one install folder). A blank path uses PATH or `molmanager/resources/bin/<platform>/`.
- **Alignment** — monospace wrap with conservation coloring (green = identical column, gold = majority, gray = gap).
- **Identity** — pairwise percent identity over columns where both sequences have a residue.
- **Export FASTA…** / **Export Clustal…** — write the aligned result.

## Workflow

1. Choose **Protein → Sequence…**.
2. Add sequences from FASTA, paste, and/or **Add from Protein Viewer**.
3. Set the MAFFT path under **Settings → Configure → MAFFT** if it is not on PATH, then **Align**.
4. Inspect the colored alignment and identity matrix; export FASTA or Clustal if needed.

## Use cases

- Align homologs or mutants from FASTA files.
- Compare polymer chains from structures already open in Protein Viewer.
- Export a Clustal block for a figure or another program.

## Tips and limits

MAFFT is not shipped in the git tree. On Windows, copy the official all-in-one folder (`mafft.bat` plus `usr/`) into `molmanager/resources/bin/win/` — see `molmanager/resources/README.md`. Missing MAFFT shows a message instead of crashing. This tool aligns amino acids only (`--amino`); nucleic-acid MSA is not supported. Phylogenetic trees are not computed.
