# BioTransformer 3.0 (optional, not in git)

**Source:** Djoumbou Feunang et al., *BioTransformer: A Comprehensive Computational Tool for Small Molecule Metabolism Prediction and Metabolite Identification*, J. Cheminform. 2019.  
https://doi.org/10.1186/s13321-018-0324-5

**License:** GNU LGPL v3. Commercial redistribution of BioTransformer resources needs explicit permission from the authors.

Install once:

```bash
python scripts/bootstrap_biotransformer.py
```

That downloads the official Bitbucket package into **this directory**. The current runnable layout is:

```
BioTransformer3.0_20230525.jar
btkb/
supportfiles/
config.json
```

Older docs used `biotransformer-3.0.0.jar` and `database/` (`bkdb/` in some snapshots). MolManager accepts any of those knowledge-base folder names next to the JAR.

You can also **Browse JAR…** under **Settings → Configure → BioTransformer**, or set `MOLMANAGER_BIOTRANSFORMER_JAR` (the knowledge-base folder and `supportfiles/` must sit next to that JAR).

Manual download: https://bitbucket.org/wishartlab/biotransformer3.0jar (source: https://github.com/Wishartlab-openscience/Biotransformer).

**Java** must be on `PATH` (`java -version`). Official docs target UNIX; on native Windows, try a current JRE first. If the JAR fails, run BioTransformer under WSL and point `MOLMANAGER_BIOTRANSFORMER_JAR` at that install.

Do not enable PubChem annotate (`-a`) from MolManager. The environmental microbial module is not offered in v1 (EnviPath non-commercial terms).
