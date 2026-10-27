# Simulation

Protein → Simulation, and Protein Viewer → Tools → Simulation, open the simulation workspace. A run is a saved document: a system, an ordered list of stages, observables, and run settings. Prepare → Minimize uses the same system builder for its one minimization stage.

## Stages

Add, duplicate, reorder, and disable stages.

- **Minimize** sets a tolerance, an iteration cap, and a restraint selection.
- **Dynamics** sets the ensemble (NVE, NVT, NPT), integrator, temperature (constant or a linear ramp), pressure, timestep, length, velocities, seed, and restraints.
- **Custom integrator** is a short OpenMM CustomIntegrator script (`variable`, `global`, `compute`, `compute_global`, `update_context`, `constrain_positions`). A bad line is reported before the first step.

A stage rebuilds the OpenMM system when its restraints, constraints, hydrogen mass, ensemble, or barostat change. Coordinates, velocities, and the box are carried forward. Pause writes `state.xml` at the next reporter interval. A checkpoint resumes an unchanged document.

## System

Build a soluble protein–ligand system here (ff14SB, ff19SB, or ff99SBildn; GAFF2, GAFF, or OpenFF; vacuum, GB, or explicit water with a cubic, octahedral, or dodecahedral box). Or import an Amber prmtop and inpcrd, an OpenMM system XML plus coordinates, or a CHARMM PSF, PDB, and parameter file. A membrane is run by importing a system you already built.

AmberTools tleap writes separate receptor, ligand, and dry-complex topologies when a GAFF ligand is parameterized. A GAFF dodecahedron is refused because tleap builds cubes and octahedra. OpenFF can use a dodecahedron.

## Observables and playback

RMSD (with a fit selection), RMSF, radius of gyration, distance, contacts, a geometric hydrogen-bond count, and MM/GBSA. MM/GBSA is E(complex) − E(receptor) − E(ligand). It omits −TΔS and is a ranking score, not the alchemical ΔΔG.

The play slider sends strided solute frames to the Protein Viewer. Solvent stays in the DCD on disk.

## Poses and free energy

**Poses** applies the document to selected table poses and asks before a queue whose production time is long. Replicates differ by seed. One OpenMM context runs at a time unless queue width is raised.

**Alchemical** mode uses the optional `fep` extra (OpenFE). The schedule is a star from a reference ligand. The two ligands must have the same net charge; a charge change stops before any lambda window and names both charges. Results are an estimate with an uncertainty, written beside the OpenFE directory.

## Files

Save the document as `.mmsim.json`. A run directory holds `manifest.json` (document hash, platform, seed, ns/day), `scalars.csv`, `trajectory.dcd`, `simulation.chk`, and `state.xml`.
