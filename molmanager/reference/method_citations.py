# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Primary literature and software references for methods beyond plain RDKit numeric descriptors.

UI and worker modules import from here so users can open DOIs and read the original methods.
"""

from __future__ import annotations

# --- Plain-text blocks (for logs, tooltips, or copying) ---------------------------------

UNIPKA = (
    "Microstate pKa (Uni-pKa): Luo, Y.; Liu, Y.; Peng, J.; Tang, H.; Nie, H.; Zhong, W.; "
    "Chen, X.; Zheng, S. Toward Universal Cell Environment pKa Prediction via Multi-task "
    "Learning. JACS Au 2024, 4, 1721. https://doi.org/10.1021/jacsau.4c00271 — "
    "https://github.com/dptech-corp/Uni-pKa — runtime https://pypi.org/project/unipkainfer/"
)

MOLGPKA = (
    "Ionization-state enumeration (MolGpKa SMARTS templates used by Uni-pKa): Pan, X.; "
    "Wang, H.; Li, C.; Zhang, J. Z. H.; Ji, C. MolGpKa: A Web Server for Small Molecule "
    "pKa Prediction Using a Graph-Convolutional Neural Network. J. Chem. Inf. Model. 2021, "
    "61 (7), 3159–3165. https://doi.org/10.1021/acs.jcim.1c00075"
)

ESOL_DELANEY = (
    "ESOL intrinsic aqueous solubility (log10 S, mol L−1): Delaney, J. S. Estimating Aqueous "
    "Solubility Directly from Molecular Structure. J. Chem. Inf. Comput. Sci. 2004, 44 (3), "
    "1000–1005. https://doi.org/10.1021/ci034243x"
)

WAGER_CNS_MPO = (
    "CNS MPO desirability score: Wager, T. T.; Verhoest, P. R.; et al. Moving beyond Rules: The "
    "Development of a Central Nervous System Multiparameter Optimization (CNS MPO) Approach To "
    "Enable Alignment of Druglike Properties. ACS Chem. Neurosci. 2010, 1 (6), 435–449. "
    "https://doi.org/10.1021/cn100008c — overview https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3368654/"
)

LOGD_LOGS_ION = (
    "LogD 7.4 and LogS 7.4 at pH 7.4: RDKit Wildman–Crippen log P (rdkit.Chem.Crippen.MolLogP) "
    "combined with the mole fraction of net-neutral protomer states at pH 7.4 from Uni-pKa "
    "ensemble Boltzmann populations (Luo et al., JACS Au 2024), the same weights as "
    "Chemistry → Prepare Structures → Protonate → Generate Protomers. "
    "log D = clogP + log10(f_neutral). Re-running after the Uni-pKa switch is a new method, "
    "not a refresh of previous pkasolver values."
)

PHARM2D_GOBBI = (
    "2D pharmacophore fingerprint (Gobbi): RDKit rdkit.Chem.Pharm2D with Gobbi_Pharm2D factory; "
    "Gobbi, A.; Poppinger, D. Genetic Optimization of Combinatorial Libraries: Variable Selection "
    "from Measurement-Free Design. Perspect. Drug Discov. Des. 1998/1999, 9–11, 123–132."
)

QED_RDKIT = (
    "QED (quantitative estimate of drug-likeness): Bickerton, G. R.; Paolini, G. V.; Besnard, J.; "
    "Muresan, S.; Leeson, P. D. Quantifying the chemical beauty of drugs. Nat. Chem. 2012, 4 (2), "
    "90–98. https://doi.org/10.1038/nchem.1243 — implemented in RDKit rdkit.Chem.QED."
)

LIPINSKI_RO5 = (
    "Rule of five counts: Lipinski, C. A.; Lombardo, F.; Dominy, B. W.; Feeney, P. J. Experimental "
    "and computational approaches to estimate solubility and permeability in drug discovery and "
    "development settings. Adv. Drug Deliv. Rev. 1997, 23 (1–3), 3–25 — RDKit Lipinski.NumHDonors / "
    "NumHAcceptors and standard limits vs MolWt / MolLogP."
)

STRUCTURAL_ALERTS = (
    "Structural alerts: RDKit FilterCatalog. PAINS: Baell, J. B.; Holloway, G. A. "
    "J. Med. Chem. 2010, 53, 2719–2740. https://doi.org/10.1021/jm901137j — "
    "Brenk: Brenk, R.; et al. ChemMedChem 2008, 3, 435–444. "
    "https://doi.org/10.1002/cmdc.200700139 — NIH, ZINC, and ChEMBL sets as shipped with RDKit."
)


def structural_alerts_dialog_footer_html() -> str:
    """Rich text for the Structural Alerts catalog method."""
    return (
        "<small><b>Catalogs</b>: RDKit FilterCatalog (BSD). "
        "<b>PAINS</b>: "
        '<a href="https://doi.org/10.1021/jm901137j">Baell &amp; Holloway, J. Med. Chem. 2010</a>. '
        "<b>Brenk</b>: "
        '<a href="https://doi.org/10.1002/cmdc.200700139">Brenk et al., ChemMedChem 2008</a>. '
        "NIH, ZINC, and ChEMBL sets are the catalogs shipped with this RDKit. "
        "A count of 0 with a blank name cell means that catalog did not match.</small>"
    )


BOILED_EGG = (
    "BOILED-Egg (TPSA vs WLOGP, GIA / BBB regions): Daina, A.; Zoete, V. A BOILED-Egg To Predict "
    "Gastrointestinal Absorption and Brain Penetration of Small Molecules. ChemMedChem 2016, 11 (11), "
    "1117–1121. https://doi.org/10.1002/cmdc.201600182 — region boundaries from supporting information; "
    "descriptors via RDKit TPSA (include S/P) and Crippen MolLogP as WLOGP."
)

GOLDEN_TRIANGLE = (
    "Golden triangle (LogP vs MW): multiparameter oral / CNS drug-likeness triangle commonly used in "
    "medicinal chemistry (e.g. Johnson et al., Drug Discov. Today 2011, 16(1-2), 65–72). "
    "MolManager draws LogP −2 to 5 and MW 200–450 Da with apex near (1.5, 450)."
)

GNN_MTL_PERMEABILITY = (
    "GNN-MTL permeability / efflux (Chemprop multitask MPNN): Ohlsson, P. I.; et al. Prediction of "
    "Permeability and Efflux Using Multitask Learning. ACS Omega 2025. "
    "https://doi.org/10.1021/acsomega.5c04861 — model artifact "
    "https://doi.org/10.5281/zenodo.16948542 (Chemprop v2.1.0, graph-only GNN-MTL)."
)

CONFAB = (
    "Confab (Open Babel systematic conformer generator): O'Boyle, N. M.; Vandermeersch, T.; "
    "Flynn, C. J.; Maguire, A. R.; Hutchison, G. R. Confab — Systematic generation of diverse "
    "low-energy conformers. J. Cheminform. 2011, 3, 8. https://doi.org/10.1186/1758-2946-3-8 — "
    "https://openbabel.org/docs/3DStructureGen/multipleconformers.html"
)

CONFORGE = (
    "CONFORGE (CDPKit conformer generator): Seidel, T.; Permann, C.; Wieder, O.; Kohlbacher, S. M.; "
    "Langer, T. High-Quality Conformer Generation with CONFORGE: Algorithm and Performance Assessment. "
    "J. Chem. Inf. Model. 2023, 63, 5549–5570. https://doi.org/10.1021/acs.jcim.3c00563 — "
    "https://cdpkit.org/applications/confgen.html"
)

OPENBABEL = (
    "Open Babel: O'Boyle, N. M.; Banck, M.; James, C. A.; Morley, C.; Vandermeersch, T.; "
    "Hutchison, G. R. Open Babel: An open chemical toolbox. J. Cheminform. 2011, 3, 33. "
    "https://doi.org/10.1186/1758-2946-3-33 — https://openbabel.org"
)


def descriptor_checkbox_citation_html(internal_key: str) -> str | None:
    """Short rich-text citation beside a Calculate Descriptors checkbox, if applicable."""
    key = (internal_key or "").strip()
    shape_html = (
        '<a href="https://doi.org/10.1021/ci025599w">Sauer &amp; Schwarz, 2003</a> '
        "(PMI / NPR shape; RDKit Descriptors3D)"
    )
    citations: dict[str, str] = {
        "LOGD74": (
            '<a href="https://doi.org/10.1021/jacsau.4c00271">Luo et al., 2024</a> '
            "(Uni-pKa) + RDKit log P / neutral fraction at pH 7.4"
        ),
        "LOGS74": (
            '<a href="https://doi.org/10.1021/jacsau.4c00271">Luo et al., 2024</a> '
            "(Uni-pKa) + RDKit log P / neutral fraction at pH 7.4"
        ),
        "LOGS_ESOL": (
            '<a href="https://doi.org/10.1021/ci034243x">Delaney, J. Chem. Inf. Comput. Sci. 2004</a> '
            "(ESOL)"
        ),
        "CNS_MPO": (
            '<a href="https://doi.org/10.1021/cn100008c">Wager et al., ACS Chem. Neurosci. 2010</a>'
        ),
        "AB_MPS": (
            '<a href="https://doi.org/10.1021/acs.jmedchem.7b00717">DeGoey et al., J. Med. Chem. 2018</a> '
            "(|LogD7.4 − 3| + aromatic rings + rotatable bonds)"
        ),
        "QED": (
            '<a href="https://doi.org/10.1038/nchem.1243">Bickerton et al., Nat. Chem. 2012</a> '
            "(RDKit QED)"
        ),
        "RO5_VIOLATIONS": "Lipinski et al., Adv. Drug Deliv. Rev. 1997 (RDKit Ro5)",
        "RO5_PASS": "Lipinski et al., Adv. Drug Deliv. Rev. 1997 (RDKit Ro5)",
        "FP_Pharm2D_Gobbi": (
            "RDKit Pharm2D; Gobbi &amp; Poppinger, <i>Perspect. Drug Discov. Des.</i> 1998"
        ),
        "COMMON_NAME": (
            '<a href="https://doi.org/10.1093/nar/gkac956">Kim et al., Nucleic Acids Res. 2023</a> '
            "(PubChem preferred name / Title)"
        ),
        "SYNONYMS": (
            '<a href="https://doi.org/10.1093/nar/gkac956">Kim et al., Nucleic Acids Res. 2023</a> '
            "(PubChem compound synonyms)"
        ),
        "PMI1": shape_html,
        "PMI2": shape_html,
        "PMI3": shape_html,
        "NPR1": shape_html,
        "NPR2": shape_html,
        "Asphericity": shape_html,
        "Eccentricity": shape_html,
        "InertialShapeFactor": shape_html,
        "RadiusOfGyration": shape_html,
        "SpherocityIndex": shape_html,
        "PBF": (
            '<a href="https://doi.org/10.1021/ci300293f">Firth, Brown &amp; Blagg, 2012</a> '
            "(plane of best fit)"
        ),
        "SASA": "RDKit rdFreeSASA (Shrake–Rupley solvent-accessible surface)",
        "MolVolume": "RDKit ComputeMolVolume",
    }
    return citations.get(key)


def descriptor_dialog_footer_html() -> str:
    """Rich text for Calculate Descriptors dialog (links open in the system browser)."""
    return (
        "<small><b>Further reading — methods not limited to a single RDKit descriptor call</b><br>"
        "<b>pKa, LogD 7.4, LogS 7.4, CNS MPO (pKa / logD legs):</b> "
        '<a href="https://doi.org/10.1021/jacsau.4c00271">Luo et al., JACS Au 2024</a>; '
        '<a href="https://github.com/dptech-corp/Uni-pKa">Uni-pKa</a> '
        '(runtime <a href="https://pypi.org/project/unipkainfer/">unipkainfer</a>).<br>'
        "<b>Ionization enumeration (Uni-pKa SMARTS):</b> "
        '<a href="https://doi.org/10.1021/acs.jcim.1c00075">Pan et al., J. Chem. Inf. Model. 2021</a> '
        "(MolGpKa templates).<br>"
        "<b>LogS intrinsic (ESOL):</b> "
        '<a href="https://doi.org/10.1021/ci034243x">Delaney, J. Chem. Inf. Comput. Sci. 2004</a>.<br>'
        "<b>CNS MPO score:</b> "
        '<a href="https://doi.org/10.1021/cn100008c">Wager et al., ACS Chem. Neurosci. 2010</a> '
        '(<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3368654/">PMC3368654</a>).<br>'
        "<b>LogD / LogS at pH 7.4:</b> RDKit <code>Crippen.MolLogP</code> + neutral protomer fractions "
        "from Uni-pKa Boltzmann populations at pH 7.4 (same ensemble as "
        "<i>Chemistry → Prepare Structures → Protonate → Generate Protomers</i>). "
        "Re-running these columns after switching from pkasolver is a new method, not a refresh.<br>"
        "<b>QED:</b> "
        '<a href="https://doi.org/10.1038/nchem.1243">Bickerton et al., Nat. Chem. 2012</a> (RDKit QED).<br>'
        "<b>Ro5:</b> Lipinski et al., Adv. Drug Deliv. Rev. 1997 (RDKit Lipinski counts).<br>"
        "<b>2D pharmacophore (Gobbi):</b> RDKit Pharm2D / Gobbi–Poppinger definitions.<br>"
        "<b>Common Name / Synonyms:</b> "
        '<a href="https://doi.org/10.1093/nar/gkac956">PubChem</a> preferred name (Title) and '
        "compound synonyms via PubChemPy (network lookup; N/A if not in PubChem).<br>"
        "<b>3D shape (PMI, NPR, asphericity, …):</b> "
        '<a href="https://doi.org/10.1021/ci025599w">Sauer &amp; Schwarz, J. Chem. Inf. Comput. Sci. 2003</a> '
        "(RDKit Descriptors3D; lowest-energy packed conformer in <code>confs</code>).<br>"
        "<b>Plane of best fit:</b> "
        '<a href="https://doi.org/10.1021/ci300293f">Firth, Brown &amp; Blagg, J. Chem. Inf. Model. 2012</a>.<br>'
        "<b>SASA / volume:</b> RDKit rdFreeSASA and ComputeMolVolume.</small>"
    )


def pka_dialog_footer_html() -> str:
    """Rich text for the Predict pKa dialog."""
    return (
        "<small><b>Method</b>: Uni-pKa free-energy microstates from "
        '<a href="https://doi.org/10.1021/jacsau.4c00271">Luo et al., JACS Au 2024</a> '
        '(<a href="https://github.com/dptech-corp/Uni-pKa">Uni-pKa</a> / '
        '<a href="https://pypi.org/project/unipkainfer/">unipkainfer</a>); ionization ensembles via '
        '<a href="https://doi.org/10.1021/acs.jcim.1c00075">MolGpKa SMARTS</a> (Pan et al., 2021). '
        "Macro pKa = (G_base − G_acid) / ln(10) for β-scaled G. First run downloads fold weights "
        "from Hugging Face (<code>unipka-download-model</code> / optional <code>model_dir</code>). "
        "Re-running after the pkasolver era is a new method, not a refresh.</small>"
    )


FAME3R_SOM = (
    "Sites of metabolism (FAME3R): Jacob, R. A.; Gaskin, L.; Seidel, T.; Chen, Y.; "
    "Mazzolari, A.; Kirchmair, J. FAME3R: an efficient, practical and reliable open-source "
    "tool for predicting phase 1 and phase 2 sites of metabolism. J. Cheminform. 2026. "
    "https://doi.org/10.1186/s13321-026-01161-1 — NERDD https://nerdd.univie.ac.at/fame3r"
)


def som_dialog_footer_html() -> str:
    """Rich text for the Predict SOM (FAME3R) dialog."""
    return (
        "<small><b>Method</b>: FAME3R random-forest sites of metabolism — "
        '<a href="https://doi.org/10.1186/s13321-026-01161-1">Jacob et al., J. Cheminform. 2026</a>; '
        'service <a href="https://nerdd.univie.ac.at/fame3r">NERDD</a>. '
        "Predicted SOM atoms are highlighted on the map (yellow→red by probability). "
        "Pre-trained MetaQSAR models are free for <b>non-commercial</b> research; "
        "commercial use requires a license from the University of Milan.</small>"
    )


def biotransformer_dialog_footer_html() -> str:
    """Rich text for the Predict Metabolites (BioTransformer) dialog."""
    return (
        "<small><b>Method</b>: BioTransformer 3 metabolite structures — "
        '<a href="https://doi.org/10.1186/s13321-018-0324-5">Djoumbou Feunang et al., '
        "J. Cheminform. 2019</a>. Local JAR only (Java on PATH). "
        "This predicts <b>products</b>, not atom sites of metabolism. "
        "LGPL-3; commercial redistribution of BioTransformer files needs author permission. "
        "Environmental microbial mode is not included.</small>"
    )


def permeability_dialog_footer_html() -> str:
    """Rich text for the permeability predictor dialog."""
    return (
        "<small><b>Method</b>: GNN-MTL multitask MPNN (Chemprop) — "
        '<a href="https://doi.org/10.1021/acsomega.5c04861">Ohlsson et al., ACS Omega 2025</a>; '
        'weights <a href="https://doi.org/10.5281/zenodo.16948542">Zenodo 10.5281/zenodo.16948542</a>. '
        "<b>Outputs</b>: linear Caco-2 ER and intrinsic Papp (Papp in ×10⁻⁶ cm/s); MDCK-MDR1 and NIH MDCK "
        "<b>efflux ratios</b> (not passive MDCK Papp). Assay conditions match AstraZeneca training data.</small>"
    )


def stochastic_conformations_dialog_footer_html() -> str:
    """Rich text for Chemistry → Conformations → Generate → Stochastic…."""
    return (
        "<small><b>Method</b>: RDKit <b>ETKDG</b> (experimental-torsion-knowledge distance geometry) — "
        '<a href="https://doi.org/10.1021/acs.jcim.5b00654">Riniker &amp; Landrum, J. Chem. Inf. Model. 2015</a>. '
        "Stochastic embedding, then MMFF/UFF or GAFF/GAFF2 (AmberTools + OpenMM) "
        "vacuum minimization and energy/RMS pruning. "
        "Energies in the results window are vacuum molecular-mechanics totals (kcal/mol), "
        "not protein-bound or quantum-chemical values. GAFF/GAFF2 need AmberTools "
        "(WSL on Windows) and OpenMM.</small>"
    )


def systematic_conformations_dialog_footer_html() -> str:
    """Rich text for Chemistry → Conformations → Generate → Systematic…."""
    return (
        "<small><b>Method</b>: Open Babel <b>Confab</b> — "
        '<a href="https://doi.org/10.1186/1758-2946-3-8">O\'Boyle et al., J. Cheminform. 2011</a>. '
        "Systematic torsion driving with RMSD and energy cutoffs (not RDKit ETKDG). "
        "Requires Open Babel (<code>obabel</code> or the Python bindings). "
        "Confab needs a 3D starting geometry; MolManager embeds with ETKDG when the ligand is 2D. "
        "Energies in the results window are vacuum MMFF/UFF totals, not protein-bound ΔG.</small>"
    )


def conforge_conformations_dialog_footer_html() -> str:
    """Rich text for Chemistry → Conformations → Generate → CONFORGE…."""
    return (
        "<small><b>Method</b>: <b>CONFORGE</b> (CDPKit) — "
        '<a href="https://doi.org/10.1021/acs.jcim.3c00563">Seidel et al., J. Chem. Inf. Model. 2023</a>. '
        "Knowledge-based fragment/torsion sampling for typical drug-like molecules; "
        "stochastic DG for large macrocycles. On Windows, install CDPKit and point at "
        "<code>confgen.exe</code> (PyPI has no Python 3.11 wheel). On Linux/macOS, "
        "<code>pip install cdpkit</code> when a wheel exists. Energies in the results window "
        "are vacuum MMFF totals, "
        "not protein-bound ΔG.</small>"
    )


def protomer_dialog_footer_html() -> str:
    """Rich text appended under the protomer generator hint."""
    return (
        "<small><b>Ionization ensemble</b>: "
        '<a href="https://doi.org/10.1021/jacsau.4c00271">Luo et al., 2024</a> / Uni-pKa. '
        "<b>Population model</b>: Boltzmann weights of β-scaled free energies at the dialog pH "
        "(same ensemble as LogD 7.4 / LogS 7.4 descriptors).</small>"
    )


SURECHEMBL = (
    "SureChEMBL (EMBL-EBI): chemistry extracted from patents and other documents; public REST API "
    "at https://www.surechembl.org/api — documentation https://chembl.gitbook.io/surechembl . "
    "Similarity search uses Tanimoto on RDKit Morgan fingerprints (256 bits, radius 2) on their "
    "servers (FPSim2-backed; see SureChEMBL chemical search documentation)."
)


def surechembl_patent_search_html() -> str:
    """Rich text for the Query Patents (SureChEMBL) dialog."""
    return (
        '<small><b>Data source</b>: <a href="https://www.surechembl.org">SureChEMBL</a> '
        "(EMBL-EBI) — compounds linked to <b>patent and document</b> chemistry, not a live Google Patents "
        "HTML search. "
        "<b>Similarity</b>: server-side Tanimoto on RDKit Morgan fingerprints (256 bits, r=2); "
        'see <a href="https://chembl.gitbook.io/surechembl/chemical-search/similarity-search-tanimoto-coefficient-and-fingerprint-generation">SureChEMBL docs</a> '
        'and <a href="https://www.ebi.ac.uk/chembl/surechembl/">SureChEMBL at ChEMBL</a>.</small>'
    )
