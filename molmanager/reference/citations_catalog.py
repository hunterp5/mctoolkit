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

"""Catalog of external tools, papers, and licenses shown in Help → Citations."""

from __future__ import annotations

from dataclasses import dataclass

# Official license texts (not restated in full here).
LIC_GPL3 = ("GNU GPL v3", "https://www.gnu.org/licenses/gpl-3.0.html")
LIC_GPL2 = ("GNU GPL v2", "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html")
LIC_LGPL21 = ("GNU LGPL v2.1", "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html")
LIC_LGPL3 = ("GNU LGPL v3", "https://www.gnu.org/licenses/lgpl-3.0.html")
LIC_APACHE2 = ("Apache License 2.0", "https://www.apache.org/licenses/LICENSE-2.0")
LIC_BSD3 = ("BSD 3-Clause", "https://opensource.org/license/bsd-3-clause")
LIC_MIT = ("MIT License", "https://opensource.org/license/mit")
LIC_PYTORCH = ("BSD-style (PyTorch)", "https://github.com/pytorch/pytorch/blob/main/LICENSE")


@dataclass(frozen=True)
class ToolCitation:
    """One external library, service, or method used by MolManager."""

    tool_id: str
    name: str
    used_in: str
    papers: tuple[tuple[str, str], ...]
    license_name: str
    license_url: str
    homepage: str = ""
    notes: str = ""


@dataclass(frozen=True)
class CitationSection:
    """Group of related tools in the Citations sidebar."""

    title: str
    tools: tuple[ToolCitation, ...]


def _t(
    tool_id: str,
    name: str,
    used_in: str,
    papers: tuple[tuple[str, str], ...],
    license_pair: tuple[str, str],
    homepage: str = "",
    notes: str = "",
) -> ToolCitation:
    return ToolCitation(
        tool_id=tool_id,
        name=name,
        used_in=used_in,
        papers=papers,
        license_name=license_pair[0],
        license_url=license_pair[1],
        homepage=homepage,
        notes=notes,
    )


CITATION_SECTIONS: tuple[CitationSection, ...] = (
    CitationSection(
        "This application",
        (
            _t(
                "molmanager",
                "MolManager",
                "Desktop chemical table workspace (this program).",
                (),
                LIC_GPL3,
                homepage="https://github.com/hunterp5/MolManager",
                notes="Copyright © 2026 Hunter Picard. Full text in the LICENSE file shipped with MolManager.",
            ),
        ),
    ),
    CitationSection(
        "Cheminformatics core",
        (
            _t(
                "rdkit",
                "RDKit",
                "Structures, 2D/3D geometry, descriptors, fingerprints, filters, "
                "BRICS/RECAP, MMPA helpers, ETKDG conformers, and table chemistry.",
                (
                    (
                        "Landrum, G. RDKit: Open-source cheminformatics. Zenodo.",
                        "https://doi.org/10.5281/zenodo.591637",
                    ),
                    (
                        "Riniker, S.; Landrum, G. A. Better Informed Distance Geometry: "
                        "Using What We Know To Improve Conformation Generation. "
                        "J. Chem. Inf. Model. 2015, 55, 2562–2574.",
                        "https://doi.org/10.1021/acs.jcim.5b00654",
                    ),
                    (
                        "Wildman, S. A.; Crippen, G. M. Prediction of Physicochemical "
                        "Parameters by Atomic Contributions. J. Chem. Inf. Comput. Sci. 1999, 39, 868–873.",
                        "https://doi.org/10.1021/ci990307l",
                    ),
                    (
                        "Ertl, P.; Rohde, B.; Selzer, P. Fast Calculation of Molecular Polar Surface Area "
                        "as a Sum of Fragment-Based Contributions. J. Med. Chem. 2000, 43, 3714–3717.",
                        "https://doi.org/10.1021/jm000942e",
                    ),
                    (
                        "Rogers, D.; Hahn, M. Extended-Connectivity Fingerprints. "
                        "J. Chem. Inf. Model. 2010, 50, 742–754.",
                        "https://doi.org/10.1021/ci100050t",
                    ),
                    (
                        "Degen, J.; Wegscheid-Gerlach, C.; Zaliani, A.; Rarey, M. On the Art of Compiling "
                        "and Using 'Drug-Like' Chemical Fragment Spaces. ChemMedChem 2008, 3, 1503–1507.",
                        "https://doi.org/10.1002/cmdc.200800178",
                    ),
                    (
                        "Lewell, X. Q.; Judd, D. B.; Watson, S. P.; Hann, M. M. RECAP—Retrosynthetic "
                        "Combinatorial Analysis Procedure. J. Chem. Inf. Comput. Sci. 1998, 38, 511–522.",
                        "https://doi.org/10.1021/ci970429i",
                    ),
                    (
                        "Hussain, J.; Rea, C. Computationally Efficient Algorithm to Identify Matched "
                        "Molecular Pairs (MMPs) in Large Data Sets. J. Chem. Inf. Model. 2010, 50, 339–348.",
                        "https://doi.org/10.1021/ci9004739",
                    ),
                    (
                        "Butina, D. Unsupervised Data Base Clustering Based on Daylight’s Fingerprint "
                        "and Tanimoto Similarity. J. Chem. Inf. Comput. Sci. 1999, 39, 747–750.",
                        "https://doi.org/10.1021/ci9803381",
                    ),
                ),
                LIC_BSD3,
                homepage="https://www.rdkit.org",
            ),
            _t(
                "openbabel",
                "Open Babel",
                "Confab systematic conformer generation (`obabel`) and related 3D utilities.",
                (
                    (
                        "O'Boyle, N. M.; et al. Open Babel: An open chemical toolbox. "
                        "J. Cheminform. 2011, 3, 33.",
                        "https://doi.org/10.1186/1758-2946-3-33",
                    ),
                    (
                        "O'Boyle, N. M.; et al. Confab — Systematic generation of diverse "
                        "low-energy conformers. J. Cheminform. 2011, 3, 8.",
                        "https://doi.org/10.1186/1758-2946-3-8",
                    ),
                ),
                LIC_GPL2,
                homepage="https://openbabel.org",
            ),
            _t(
                "conforge",
                "CONFORGE (CDPKit)",
                "Knowledge-based conformer ensembles (Tools → Conformations → Generate → CONFORGE).",
                (
                    (
                        "Seidel, T.; Permann, C.; Wieder, O.; Kohlbacher, S. M.; Langer, T. "
                        "High-Quality Conformer Generation with CONFORGE: Algorithm and "
                        "Performance Assessment. J. Chem. Inf. Model. 2023, 63, 5549–5570.",
                        "https://doi.org/10.1021/acs.jcim.3c00563",
                    ),
                ),
                LIC_LGPL3,
                homepage="https://cdpkit.org",
                notes="Optional. Windows 3.11: CDPKit MSVC installer (confgen.exe). Linux/macOS: pip install cdpkit when a wheel exists.",
            ),
            _t(
                "3dmol",
                "3Dmol.js",
                "In-app 2D/3D structure viewer (bundled `3Dmol-min.js`).",
                (
                    (
                        "Rego, N.; Koes, D. 3Dmol.js: molecular visualization with WebGL. "
                        "Bioinformatics 2015, 31, 1322–1324.",
                        "https://doi.org/10.1093/bioinformatics/btu829",
                    ),
                ),
                LIC_BSD3,
                homepage="https://3dmol.org",
            ),
            _t(
                "mafft",
                "MAFFT",
                "Protein → Sequence multiple-sequence alignment (`mafft --auto --amino`).",
                (
                    (
                        "Katoh, K.; Misawa, K.; Kuma, K.; Miyata, T. MAFFT: a novel method for "
                        "rapid multiple sequence alignment based on fast Fourier transform. "
                        "Nucleic Acids Res. 2002, 30, 3059–3066.",
                        "https://doi.org/10.1093/nar/gkf436",
                    ),
                    (
                        "Katoh, K.; Standley, D. M. MAFFT multiple sequence alignment software "
                        "version 7: improvements in performance and usability. Mol. Biol. Evol. "
                        "2013, 30, 772–780.",
                        "https://doi.org/10.1093/molbev/mst010",
                    ),
                ),
                LIC_BSD3,
                homepage="https://mafft.cbrc.jp/alignment/software/",
                notes=(
                    "Optional local CLI. Do not commit the Windows all-in-one tree; drop "
                    "`mafft.bat` (with its `usr/` folder) into `molmanager/resources/bin/win/` "
                    "or put `mafft` on PATH. Official Windows zip: "
                    "https://mafft.cbrc.jp/alignment/software/windows.html"
                ),
            ),
        ),
    ),
    CitationSection(
        "Ionization, pKa, and ADME models",
        (
            _t(
                "unipka",
                "Uni-pKa (unipkainfer)",
                "Predict pKa, Protonate, Generate Protomers, Protein Viewer Prepare ligand "
                "protomer, and pH-dependent LogD/LogS 7.4, CNS MPO, and AB-MPS ionization legs.",
                (
                    (
                        "Luo, Y.; et al. Toward Universal Cell Environment pKa Prediction via "
                        "Multi-task Learning. JACS Au 2024, 4, 1721.",
                        "https://doi.org/10.1021/jacsau.4c00271",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://github.com/dptech-corp/Uni-pKa",
                notes="Runtime package: https://pypi.org/project/unipkainfer/",
            ),
            _t(
                "molgpka",
                "MolGpKa SMARTS templates",
                "Ionization-state enumeration used by Uni-pKa (vendored TSV under resources/unipka).",
                (
                    (
                        "Pan, X.; et al. MolGpKa: A Web Server for Small Molecule pKa Prediction "
                        "Using a Graph-Convolutional Neural Network. J. Chem. Inf. Model. 2021, 61, 3159–3165.",
                        "https://doi.org/10.1021/acs.jcim.1c00075",
                    ),
                ),
                LIC_MIT,
                homepage="https://github.com/Xundrug/MolGpKa",
                notes="See molmanager/resources/unipka/NOTICE.md. These files are third-party data, not MolManager GPL source.",
            ),
            _t(
                "fame3r",
                "FAME3R",
                "Predict SOM (sites of metabolism) via the NERDD FAME3R web service.",
                (
                    (
                        "Jacob, R. A.; et al. FAME3R: an efficient, practical and reliable open-source "
                        "tool for predicting phase 1 and phase 2 sites of metabolism. J. Cheminform. 2026.",
                        "https://doi.org/10.1186/s13321-026-01161-1",
                    ),
                ),
                ("See FAME3R / MetaQSAR terms", "https://nerdd.univie.ac.at/fame3r"),
                homepage="https://nerdd.univie.ac.at/fame3r",
                notes=(
                    "Pre-trained MetaQSAR models are free for non-commercial research. "
                    "Commercial use requires a license from the University of Milan. "
                    "Confirm current terms with the FAME3R authors before commercial deployment."
                ),
            ),
            _t(
                "biotransformer",
                "BioTransformer",
                "Predict Metabolites via a local BioTransformer 3 JAR (CYP450, Phase II, gut, allHuman).",
                (
                    (
                        "Djoumbou Feunang, Y.; et al. BioTransformer: A Comprehensive Computational "
                        "Tool for Small Molecule Metabolism Prediction and Metabolite Identification. "
                        "J. Cheminform. 2019, 11, 2.",
                        "https://doi.org/10.1186/s13321-018-0324-5",
                    ),
                ),
                LIC_LGPL3,
                homepage="https://biotransformer.ca",
                notes=(
                    "GNU LGPL v3. Place the JAR plus database/ and supportfiles/ next to it "
                    "(or set MOLMANAGER_BIOTRANSFORMER_JAR). Commercial redistribution of "
                    "BioTransformer resources requires permission from the authors. Java must "
                    "be on PATH. Environmental microbial predictions are not offered in MolManager."
                ),
            ),
            _t(
                "chemprop",
                "Chemprop (GNN-MTL permeability)",
                "Predict Permeability / efflux (Caco-2, MDCK) via a Chemprop multitask MPNN.",
                (
                    (
                        "Yang, K.; et al. Analyzing Learned Molecular Representations for Property Prediction. "
                        "J. Chem. Inf. Model. 2019, 59, 3370–3388.",
                        "https://doi.org/10.1021/acs.jcim.9b00237",
                    ),
                    (
                        "Heid, E.; et al. Chemprop: A Machine Learning Package for Chemical Property Prediction. "
                        "J. Chem. Inf. Model. 2024, 64, 9–17.",
                        "https://doi.org/10.1021/acs.jcim.3c01250",
                    ),
                    (
                        "Ohlsson, P. I.; et al. Prediction of Permeability and Efflux Using Multitask Learning. "
                        "ACS Omega 2025.",
                        "https://doi.org/10.1021/acsomega.5c04861",
                    ),
                    (
                        "GNN-MTL model weights (Zenodo 10.5281/zenodo.16948542).",
                        "https://doi.org/10.5281/zenodo.16948542",
                    ),
                ),
                LIC_MIT,
                homepage="https://github.com/chemprop/chemprop",
            ),
            _t(
                "cns_mpo",
                "CNS MPO (Wager)",
                "CNS multiparameter optimization score (descriptor / MPO tools).",
                (
                    (
                        "Wager, T. T.; et al. Moving beyond Rules: The Development of a Central Nervous System "
                        "Multiparameter Optimization (CNS MPO) Approach. ACS Chem. Neurosci. 2010, 1, 435–449.",
                        "https://doi.org/10.1021/cn100008c",
                    ),
                ),
                LIC_GPL3,
                homepage="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3368654/",
                notes="Score implemented in MolManager (this GPL program) using RDKit descriptors plus Uni-pKa ionization.",
            ),
            _t(
                "esol",
                "ESOL (Delaney)",
                "Intrinsic aqueous solubility (LogS ESOL descriptor).",
                (
                    (
                        "Delaney, J. S. Estimating Aqueous Solubility Directly from Molecular Structure. "
                        "J. Chem. Inf. Comput. Sci. 2004, 44, 1000–1005.",
                        "https://doi.org/10.1021/ci034243x",
                    ),
                ),
                LIC_GPL3,
                notes="Published ESOL model, implemented in MolManager (this GPL program).",
            ),
            _t(
                "qed",
                "QED",
                "Quantitative estimate of drug-likeness (RDKit QED).",
                (
                    (
                        "Bickerton, G. R.; et al. Quantifying the chemical beauty of drugs. "
                        "Nat. Chem. 2012, 4, 90–98.",
                        "https://doi.org/10.1038/nchem.1243",
                    ),
                ),
                LIC_BSD3,
                notes="Calculated via rdkit.Chem.QED (RDKit BSD license).",
            ),
            _t(
                "lipinski",
                "Lipinski Rule of Five",
                "Ro5 pass / violation counts.",
                (
                    (
                        "Lipinski, C. A.; et al. Experimental and computational approaches to estimate "
                        "solubility and permeability. Adv. Drug Deliv. Rev. 1997, 23, 3–25.",
                        "https://doi.org/10.1016/S0169-409X(96)00423-1",
                    ),
                ),
                LIC_BSD3,
                notes="Counts via RDKit Lipinski helpers.",
            ),
            _t(
                "ab_mps",
                "AB-MPS",
                "AbbVie MPS-style score from |LogD7.4 − 3| + aromatic rings + rotatable bonds.",
                (
                    (
                        "DeGoey, D. A.; Chen, H.-J.; Cox, P. B.; Wendt, M. D. Beyond the Rule of 5: "
                        "Lessons Learned from AbbVie's Drugs and Compound Collection. "
                        "J. Med. Chem. 2018, 61, 2636–2651.",
                        "https://doi.org/10.1021/acs.jmedchem.7b00717",
                    ),
                ),
                LIC_GPL3,
                notes="Implemented in MolManager; ionization from Uni-pKa. Values ≤ 14 are often associated with higher oral/PK success in bRo5 space.",
            ),
            _t(
                "pharm2d_gobbi",
                "Gobbi 2D pharmacophore fingerprint",
                "RDKit Pharm2D Gobbi fingerprint (Calculate Descriptors / fingerprint tools).",
                (
                    (
                        "Gobbi, A.; Poppinger, D. Genetic Optimization of Combinatorial Libraries: "
                        "Variable Selection from Measurement-Free Design. Perspect. Drug Discov. Des. "
                        "1998/1999, 9–11, 123–132.",
                        "",
                    ),
                ),
                LIC_BSD3,
                notes="Fingerprint code is RDKit (BSD 3-Clause); the pharmacophore definitions follow Gobbi & Poppinger.",
            ),
            _t(
                "rdkit_pharma3d",
                "RDKit 3D pharmacophore features",
                "Protein Viewer → Tools → Pharmacophore (From ligand), Gnina pose filtering, "
                "and Tools → Conformations → Screen Pharmacophore.",
                (
                    (
                        "Landrum, G. RDKit: Open-source cheminformatics. Zenodo.",
                        "https://doi.org/10.5281/zenodo.591637",
                    ),
                ),
                LIC_BSD3,
                homepage="https://www.rdkit.org",
                notes=(
                    "Feature families from RDKit BaseFeatures.fdef (Donor, Acceptor, Aromatic, "
                    "Hydrophobe, LumpedHydrophobe, PosIonizable, NegIonizable, ZnBinder). "
                    "MolManager stores spheres as JSON. Docked poses are filtered in the "
                    "protein frame (RDKit feature type + sphere radius). "
                    "Ensemble screening matches RDKit feature types and pairwise distances "
                    "(Exclusion volumes are skipped)."
                ),
            ),
        ),
    ),
    CitationSection(
        "Docking and biomolecular simulation",
        (
            _t(
                "gnina",
                "Gnina",
                "Protein → Dock Ligand → Gnina (file-based docking with CNN scoring).",
                (
                    (
                        "McNutt, A. T.; Li, Y.; Meli, R.; Aggarwal, R.; Koes, D. R. "
                        "GNINA 1.3: the next increment in molecular docking with deep learning. "
                        "J. Cheminformatics 2025, 17, 28.",
                        "https://doi.org/10.1186/s13321-025-00973-x",
                    ),
                    (
                        "McNutt, A. T.; Francoeur, P.; Aggarwal, R.; Masuda, T.; Meli, R.; Ragoza, M.; "
                        "Sunseri, J.; Koes, D. R. GNINA 1.0: molecular docking with deep learning. "
                        "J. Cheminformatics 2021, 13, 43.",
                        "https://doi.org/10.1186/s13321-021-00522-2",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://github.com/gnina/gnina",
                notes=(
                    "After docking, MolManager keeps poses whose RDKit feature sites occupy "
                    "the Protein Viewer pharmacophore spheres (protein coordinates). Gnina "
                    "--user_grid occupancy maps are not used."
                ),
            ),
            _t(
                "vina",
                "AutoDock Vina",
                "Gnina and Smina are forks of AutoDock Vina; pose logs may include VINA RESULT remarks.",
                (
                    (
                        "Trott, O.; Olson, A. J. AutoDock Vina: Improving the speed and accuracy of docking "
                        "with a new scoring function, efficient optimization, and multithreading. "
                        "J. Comput. Chem. 2010, 31, 455–461.",
                        "https://doi.org/10.1002/jcc.21334",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://github.com/ccsb-scripps/AutoDock-Vina",
            ),
            _t(
                "smina",
                "Smina",
                "Ancestor of Gnina; empirical Vina-style scoring used when CNN scoring is None.",
                (
                    (
                        "Koes, D. R.; Baumgartner, M. P.; Camacho, C. J. Lessons Learned in Empirical Scoring "
                        "with smina from the CSAR 2011 Benchmarking Exercise. J. Chem. Inf. Model. 2013, 53, 1893–1904.",
                        "https://doi.org/10.1021/ci300604z",
                    ),
                ),
                LIC_GPL2,
                homepage="https://sourceforge.net/projects/smina/",
            ),
            _t(
                "meeko",
                "Meeko",
                "Ligand PDBQT preparation for docking.",
                (
                    (
                        "Forli Lab. Meeko: preparation of small molecules for AutoDock. GitHub.",
                        "https://github.com/forlilab/Meeko",
                    ),
                ),
                LIC_LGPL21,
                homepage="https://github.com/forlilab/Meeko",
            ),
            _t(
                "openmm",
                "OpenMM",
                "Optional docking extra: PDBFixer backend and Protein Viewer restrained minimization.",
                (
                    (
                        "Eastman, P.; et al. OpenMM 7: Rapid development of high performance algorithms "
                        "for molecular dynamics. PLoS Comput. Biol. 2017, 13, e1005659.",
                        "https://doi.org/10.1371/journal.pcbi.1005659",
                    ),
                    (
                        "Nguyen, H.; Roe, D. R.; Simmerling, C. Improved Generalized Born Solvent "
                        "Model Parameters for Protein Simulations. J. Chem. Theory Comput. 2013, "
                        "9, 2020–2034.",
                        "https://doi.org/10.1021/ct3010485",
                    ),
                ),
                LIC_MIT,
                homepage="https://openmm.org",
                notes=(
                    "Protein Viewer Prepare minimization defaults to GBn2 GBSA with 0.15 M salt "
                    "and backbone restraints (Cα, vacuum, or GAFF/GAFF2 holo min optional). "
                    "OpenMM also includes LGPL components; see the OpenMM license files in that package."
                ),
            ),
            _t(
                "ambertools",
                "AmberTools",
                "Protein Viewer Prepare: GAFF/GAFF2 ligand parameterization (antechamber, "
                "parmchk2, tleap) for OpenMM holo minimization. Stochastic conformer "
                "generation: vacuum GAFF/GAFF2 minimization of ETKDG poses. On Windows "
                "AmberTools runs in WSL.",
                (
                    (
                        "Case, D. A.; et al. AmberTools. J. Chem. Inf. Model. 2023, 63, 6183–6191.",
                        "https://doi.org/10.1021/acs.jcim.3c01153",
                    ),
                    (
                        "Wang, J.; Wolf, R. M.; Caldwell, J. W.; Kollman, P. A.; Case, D. A. "
                        "Development and testing of a general amber force field. "
                        "J. Comput. Chem. 2004, 25, 1157–1174.",
                        "https://doi.org/10.1002/jcc.20035",
                    ),
                ),
                LIC_GPL3,
                homepage="https://ambermd.org/AmberTools.php",
                notes=(
                    "GAFF2 is the default small-molecule field when Ligand force field is GAFF2. "
                    "AM1-BCC charges use sqm; Gasteiger is the fallback if BCC fails. "
                    "Conformer generation uses the same parameterization in vacuum."
                ),
            ),
            _t(
                "pdbfixer",
                "PDBFixer",
                "Prepare PDB receptors (missing atoms/residues) before docking.",
                (
                    (
                        "Eastman, P. PDBFixer. GitHub (OpenMM ecosystem).",
                        "https://github.com/openmm/pdbfixer",
                    ),
                ),
                LIC_MIT,
                homepage="https://github.com/openmm/pdbfixer",
            ),
            _t(
                "pdb2pqr",
                "PDB2PQR",
                "Protein Viewer Prepare: pH-based protonation and hydrogen placement.",
                (
                    (
                        "Dolinsky, T. J.; et al. PDB2PQR: expanding and upgrading automated "
                        "preparation of biomolecular structures for molecular simulations. "
                        "Nucleic Acids Res. 2007, 35, W522–W525.",
                        "https://doi.org/10.1093/nar/gkm276",
                    ),
                    (
                        "Olsson, M. H. M.; Søndergaard, C. R.; Rostkowski, M.; Jensen, J. H. "
                        "PROPKA3: Consistent Treatment of Internal and Surface Residues in "
                        "Empirical pKa Predictions. J. Chem. Theory Comput. 2011, 7, 525–537.",
                        "https://doi.org/10.1021/ct100578z",
                    ),
                ),
                LIC_BSD3,
                homepage="https://pdb2pqr.readthedocs.io/",
                notes="PROPKA assigns protein titration states at the chosen pH. Ligand ionization is Uni-pKa, not PROPKA.",
            ),
            _t(
                "prolif",
                "ProLIF",
                "Protein Viewer Render → Interactions: protein–ligand hydrogen bonds, "
                "hydrophobic contacts, salt bridges, π-stacking, π-cation, and halogen bonds.",
                (
                    (
                        "Bouysset, C.; Fiorucci, S. ProLIF: a library to encode molecular "
                        "interactions as fingerprints. J. Cheminform. 2021, 13, 72.",
                        "https://doi.org/10.1186/s13321-021-00548-6",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://github.com/chemosim-lab/ProLIF",
                notes=(
                    "Optional docking extra (`pip install prolif`). Intramolecular protein and "
                    "ligand hydrogen bonds still use MolManager's geometric detector. "
                    "Protein–ligand H-bonds fall back to that detector when ProLIF is missing "
                    "or hydrogens are absent. Pose Browser overlays recompute ProLIF against "
                    "the receptor only (cached protein molecule; crystal ligand ignored)."
                ),
            ),
        ),
    ),
    CitationSection(
        "Plots, embeddings, and statistics",
        (
            _t(
                "sklearn",
                "scikit-learn",
                "PCA, t-SNE, clustering helpers, and numeric preprocessing.",
                (
                    (
                        "Pedregosa, F.; et al. Scikit-learn: Machine Learning in Python. "
                        "J. Mach. Learn. Res. 2011, 12, 2825–2830.",
                        "https://jmlr.org/papers/v12/pedregosa11a.html",
                    ),
                    (
                        "van der Maaten, L.; Hinton, G. Visualizing Data using t-SNE. "
                        "J. Mach. Learn. Res. 2008, 9, 2579–2605.",
                        "https://jmlr.org/papers/v9/vandermaaten08a.html",
                    ),
                ),
                LIC_BSD3,
                homepage="https://scikit-learn.org",
            ),
            _t(
                "umap",
                "UMAP (umap-learn)",
                "Data → DimRed Plots → UMAP Visualization.",
                (
                    (
                        "McInnes, L.; Healy, J.; Melville, J. UMAP: Uniform Manifold Approximation "
                        "and Projection for Dimension Reduction. 2018.",
                        "https://arxiv.org/abs/1802.03426",
                    ),
                    (
                        "McInnes, L.; Healy, J.; Saul, N.; Großberger, L. UMAP: Uniform Manifold "
                        "Approximation and Projection. JOSS 2018, 3, 861.",
                        "https://doi.org/10.21105/joss.00861",
                    ),
                ),
                LIC_BSD3,
                homepage="https://github.com/lmcinnes/umap",
            ),
            _t(
                "som",
                "Self-organizing map (Kohonen)",
                "Data → DimRed Plots → Self-Organizing Map (NumPy implementation in MolManager).",
                (
                    (
                        "Kohonen, T. Self-Organized Formation of Topologically Correct Feature Maps. "
                        "Biol. Cybern. 1982, 43, 59–69.",
                        "https://doi.org/10.1007/BF00337288",
                    ),
                ),
                LIC_GPL3,
                notes="Algorithm citation; the MolManager SOM code is part of this GPL program.",
            ),
            _t(
                "plotly",
                "Plotly",
                "Plotter and interactive embedding/medchem plots (Qt WebEngine).",
                (
                    (
                        "Plotly Technologies Inc. Collaborative data science. 2015.",
                        "https://plotly.com",
                    ),
                ),
                LIC_MIT,
                homepage="https://github.com/plotly/plotly.py",
            ),
            _t(
                "boiled_egg",
                "BOILED-Egg",
                "Data → MedChem Plots → BOILED-Egg plot (TPSA vs WLOGP regions).",
                (
                    (
                        "Daina, A.; Zoete, V. A BOILED-Egg To Predict Gastrointestinal Absorption "
                        "and Brain Penetration of Small Molecules. ChemMedChem 2016, 11, 1117–1121.",
                        "https://doi.org/10.1002/cmdc.201600182",
                    ),
                ),
                LIC_GPL3,
                notes="Region boundaries from the publication SI; descriptors via RDKit. Plot implemented in MolManager.",
            ),
            _t(
                "golden_triangle",
                "Golden Triangle",
                "Data → MedChem Plots → Golden Triangle plot (LogP vs MW).",
                (
                    (
                        "Johnson, T. W.; Dress, K. R.; Edwards, M. Using the Golden Triangle to "
                        "optimize clearance and oral absorption. Bioorg. Med. Chem. Lett. 2009, 19, 5560–5564.",
                        "https://doi.org/10.1016/j.bmcl.2009.08.045",
                    ),
                ),
                LIC_GPL3,
                notes="Plot implemented in MolManager (LogP −2 to 5, MW 200–450 Da, apex near 1.5 / 450).",
            ),
            _t(
                "sali",
                "SALI",
                "Data → SALI (structure–activity landscape index).",
                (
                    (
                        "Guha, R.; Van Drie, J. H. Structure−Activity Landscape Index: Identifying "
                        "and Quantifying Activity Cliffs. J. Chem. Inf. Model. 2008, 48, 646–658.",
                        "https://doi.org/10.1021/ci7004093",
                    ),
                ),
                LIC_GPL3,
                notes="SALI = |Δactivity| / (1 − similarity). Implemented in MolManager using RDKit fingerprints.",
            ),
            _t(
                "free_wilson",
                "Free-Wilson",
                "Data → Free-Wilson (additive substituent contributions on a shared core).",
                (
                    (
                        "Free, S. M.; Wilson, J. W. A Mathematical Contribution to Structure-Activity "
                        "Studies. J. Med. Chem. 1964, 7, 395–399.",
                        "https://doi.org/10.1021/jm00334a001",
                    ),
                    (
                        "Fujita, T.; Ban, T. Structure-Activity Study of Phenethylamines as Substrates "
                        "of Biosynthetic Enzymes of Sympathetic Transmitters. J. Med. Chem. 1971, 14, 148–152.",
                        "https://doi.org/10.1021/jm00284a016",
                    ),
                ),
                LIC_GPL3,
                notes=(
                    "One additive least-squares fit. Fujita-Ban (default) reports the change versus "
                    "a reference substituent; classic Free-Wilson recenters the same fit so "
                    "occurrence-weighted coefficients sum to zero. Implemented in MolManager."
                ),
            ),
        ),
    ),
    CitationSection(
        "External databases",
        (
            _t(
                "pubchem",
                "PubChem / PubChemPy",
                "Tools → Query Database → PubChem; Tools → Utilities → Random → Molecule; Calculate Descriptors → Name (Common Name, Synonyms).",
                (
                    (
                        "Kim, S.; et al. PubChem 2023 update. Nucleic Acids Res. 2023, 51, D1373–D1380.",
                        "https://doi.org/10.1093/nar/gkac956",
                    ),
                ),
                LIC_MIT,
                homepage="https://pubchem.ncbi.nlm.nih.gov",
                notes="PubChem data are U.S. government works; PubChemPy is MIT. Respect NCBI usage policies.",
            ),
            _t(
                "chembl",
                "ChEMBL",
                "Tools → Query Database → ChEMBL (`chembl_webresource_client`); Tools → Utilities → Random → Molecule.",
                (
                    (
                        "Zdrazil, B.; et al. The ChEMBL Database in 2023. Nucleic Acids Res. 2024, 52, D1180–D1192.",
                        "https://doi.org/10.1093/nar/gkad1004",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://www.ebi.ac.uk/chembl",
                notes="ChEMBL data have their own terms of use (CC BY-SA for much of the database). The Python client is Apache-2.0.",
            ),
            _t(
                "zinc",
                "ZINC",
                "Tools → Utilities → Random → Molecule (ZINC source).",
                (
                    (
                        "Tingle, B. I.; Tang, K. G.; Castanon, M.; et al. ZINC-22—A Free Multi-Billion-Scale "
                        "Database of Tangible Compounds for Ligand Discovery. J. Chem. Inf. Model. 2023, "
                        "63, 585–594.",
                        "https://doi.org/10.1021/acs.jcim.2c01253",
                    ),
                    (
                        "Irwin, J. J.; et al. ZINC20—A Free Ultralarge-Scale Chemical Database for "
                        "Ligand Discovery. J. Chem. Inf. Model. 2020, 60, 6065–6073.",
                        "https://doi.org/10.1021/acs.jcim.0c00675",
                    ),
                ),
                ("ZINC terms of use", "https://zinc.docking.org"),
                homepage="https://zinc.docking.org",
                notes="Random substances via the public ZINC22 CartBlanche API. ZINC data have their own terms of use.",
            ),
            _t(
                "surechembl",
                "SureChEMBL",
                "Tools → Query Database → Patents.",
                (
                    (
                        "Papadatos, G.; et al. SureChEMBL: a large-scale, chemically annotated patent document database. "
                        "Nucleic Acids Res. 2016, 44, D1220–D1228.",
                        "https://doi.org/10.1093/nar/gkv1253",
                    ),
                ),
                ("EMBL-EBI terms of use", "https://www.ebi.ac.uk/about/terms-of-use"),
                homepage="https://www.surechembl.org",
                notes="Patent chemistry via the SureChEMBL REST API. Similarity search uses server-side Morgan fingerprints.",
            ),
        ),
    ),
    CitationSection(
        "GUI, numerics, and ML runtime",
        (
            _t(
                "pyqt",
                "PyQt5 / Qt",
                "Desktop UI (tables, dialogs, menus).",
                (
                    (
                        "The Qt Company. Qt documentation.",
                        "https://doc.qt.io",
                    ),
                ),
                LIC_GPL3,
                homepage="https://www.riverbankcomputing.com/software/pyqt/",
                notes="PyQt5 is GPL v3, or a commercial Riverbank license. Qt itself has LGPL/GPL/commercial options.",
            ),
            _t(
                "pyqtwebengine",
                "PyQtWebEngine (Chromium)",
                "3Dmol viewer, Plotly, and other embedded HTML views.",
                (
                    (
                        "The Qt Company. Qt WebEngine.",
                        "https://doc.qt.io/qt-5/qtwebengine-index.html",
                    ),
                ),
                LIC_GPL3,
                homepage="https://www.riverbankcomputing.com/software/pyqt/",
                notes="WebEngine bundles Chromium under BSD-style and other licenses; see Qt WebEngine third-party notices.",
            ),
            _t(
                "numpy",
                "NumPy",
                "Numeric arrays (descriptors, SOM, embeddings).",
                (
                    (
                        "Harris, C. R.; et al. Array programming with NumPy. Nature 2020, 585, 357–362.",
                        "https://doi.org/10.1038/s41586-020-2649-2",
                    ),
                ),
                LIC_BSD3,
                homepage="https://numpy.org",
            ),
            _t(
                "pandas",
                "pandas",
                "Tabular intermediates (imports, Uni-pKa results, some workers).",
                (
                    (
                        "McKinney, W. Data Structures for Statistical Computing in Python. "
                        "Proc. SciPy 2010, 56–61.",
                        "https://doi.org/10.25080/Majora-92bf1922-00a",
                    ),
                ),
                LIC_BSD3,
                homepage="https://pandas.pydata.org",
            ),
            _t(
                "scipy",
                "SciPy",
                "Scientific routines used with embeddings and numerics.",
                (
                    (
                        "Virtanen, P.; et al. SciPy 1.0: fundamental algorithms for scientific computing "
                        "in Python. Nat. Methods 2020, 17, 261–272.",
                        "https://doi.org/10.1038/s41592-019-0686-2",
                    ),
                ),
                LIC_BSD3,
                homepage="https://scipy.org",
            ),
            _t(
                "sqlalchemy",
                "SQLAlchemy",
                "Tools → Query Database → SQL; and the local table index.",
                (
                    (
                        "Bayer, M. SQLAlchemy. GitHub.",
                        "https://www.sqlalchemy.org",
                    ),
                ),
                LIC_MIT,
                homepage="https://www.sqlalchemy.org",
            ),
            _t(
                "torch",
                "PyTorch",
                "Uni-pKa and Chemprop extras (CPU or CUDA wheel).",
                (
                    (
                        "Paszke, A.; et al. PyTorch: An Imperative Style, High-Performance Deep Learning Library. "
                        "NeurIPS 2019.",
                        "https://doi.org/10.48550/arXiv.1912.01703",
                    ),
                ),
                LIC_PYTORCH,
                homepage="https://pytorch.org",
            ),
            _t(
                "lightning",
                "PyTorch Lightning",
                "Optional permeability extra (Chemprop training/inference stack).",
                (
                    (
                        "Falcon, W.; The PyTorch Lightning team. PyTorch Lightning.",
                        "https://github.com/Lightning-AI/pytorch-lightning",
                    ),
                ),
                LIC_APACHE2,
                homepage="https://lightning.ai",
            ),
        ),
    ),
)


def iter_tool_citations() -> list[ToolCitation]:
    out: list[ToolCitation] = []
    for section in CITATION_SECTIONS:
        out.extend(section.tools)
    return out


def tool_citation(tool_id: str) -> ToolCitation | None:
    for tool in iter_tool_citations():
        if tool.tool_id == tool_id:
            return tool
    return None


def _paper_item(title: str, url: str) -> str:
    if url:
        return f'<li><a href="{url}">{_escape(title)}</a></li>'
    return f"<li>{_escape(title)}</li>"


def tool_citation_html_fragment(tool: ToolCitation) -> str:
    """HTML body for one tool (no surrounding document)."""
    papers = "".join(_paper_item(title, url) for title, url in tool.papers)
    papers_block = (
        f"<h3>Papers and references</h3><ul>{papers}</ul>"
        if papers
        else "<h3>Papers and references</h3><p>No journal article is cited for this component; see the homepage.</p>"
    )
    home = (
        f'<p>Homepage: <a href="{tool.homepage}">{_escape(tool.homepage)}</a></p>'
        if tool.homepage
        else ""
    )
    notes = f"<p>{_escape(tool.notes)}</p>" if tool.notes else ""
    return (
        f"<h1>{_escape(tool.name)}</h1>"
        f"<p>{_escape(tool.used_in)}</p>"
        f"{papers_block}"
        f"<h3>License</h3>"
        f'<p>Licensing agreement: <a href="{tool.license_url}">{_escape(tool.license_name)}</a>. '
        "MolManager links the official license rather than reproducing the full legal text here. "
        "Install the upstream package or open the URL for the binding agreement.</p>"
        f"{home}{notes}"
    )


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
