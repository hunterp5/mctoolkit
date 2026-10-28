# Preparation Menu

Preparation Menu is the checklist for standardizing structures. A run includes only the options that are checked. Every option starts unchecked.

## Goal

Put cleanup, the organic parent, tautomers, charge, hydrogens, protomers, and depiction in one place. pKa prediction and substructure alignment stay in their own dialogs. For a fixed largest-fragment cleanup, use **Chemistry → Structure Preparation → Fast Prepare…**.

## When to use

Open it from **Chemistry → Structure Preparation → Preparation Menu…**. Use it on imported structures before descriptors, clustering, or a model. Turn on only the steps you want.

## Options

**Options**

- **Standardize** removes explicit hydrogens, disconnects metal–organic bonds, normalizes functional groups, and reionizes. Reionize moves a proton between equivalent sites. It is not a pH 7.4 form.
- **Largest organic fragment** keeps the organic parent. Other pieces are written to the fragments column.
- **Canonical tautomer** maps equivalent tautomers onto one structure. The search stops after 100 transforms, so a very large molecule may differ from an exhaustive tautomer. RDKit drops tetrahedral and double-bond stereo while doing this.
- **Render 2D** redraws the result. The current orientation is kept when the atom count does not change.

**Protonation and neutralization**

- **Neutralize** zeros the net formal charge. It does not set a physiological form.
- **Protonate** writes the dominant protomer at a pH (default 7.40), plus the population and **pKa**. Checking it turns Neutralize off, and the reverse.
- **Generate protomers** enumerates forms at a pH and shows them so rows can be added. An optional SDF or CSV path writes every protomer when generation finishes.

**Explicit hydrogens and isotope labels**

- **Add explicit hydrogens** and **Remove explicit hydrogens** only show or hide valence hydrogens. They do not change formal charge or protonation. Checking one turns the other off.
- **Remove isotope labels** clears mass numbers such as deuterium.

## Output

**Update Target Column** writes back into the chosen structure column. **New Column** writes the prepared structure under another name. Canonical SMILES is how a text column stores the result.

## Workflow

1. Choose the structure column and, when needed, selected rows only.
2. Check the steps you want. Leave the rest off.
3. Run and spot-check charges, tautomers, and depictions.

## Use cases

- Standardize a vendor file and keep the organic parent.
- Protonate at pH 7.4 without also canonicalizing tautomers.
- Strip isotope labels while leaving the charge state alone.

## Tips and limits

The largest-fragment step can drop a counter-ion you meant to keep; the fragments column lists what was removed. Neutralize and Protonate are two different charge models, so only one stays checked. Tautomer canonicalization can move a double bond and drop stereo. A saved Fast Prepare recipe that has none of these options still keeps the largest fragment, neutralizes only if that was saved, and redraws.
