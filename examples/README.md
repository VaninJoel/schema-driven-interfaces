# Example runs

One parameter sweep for each case study, made with the released **v1.0.3**
Windows installer the way a user would:
1. Open the app and enter an experiment name and the operator name.
2. Type a comma-separated list of values into one parameter field.
3. Set the number of replicates and press **Run Simulation**.

Every other parameter stayed at its schema default.

| Case study | Sweep | Experiment report (start here) | Per-combination reports |
|---|---|---|---|
| **Angio-GUI** (integrated pattern) | Chemotaxis strength `lchem` = 100, 500, 1000 × 3 replicates (9 runs) | [experiment report](angio-gui_lchem_sweep/angio_lchem_sweep_20261020_182022_experiment_report.pdf) | [lchem=100](angio-gui_lchem_sweep/angio_lchem_sweep_combo001_omex_report.pdf) · [lchem=500](angio-gui_lchem_sweep/angio_lchem_sweep_combo002_omex_report.pdf) · [lchem=1000](angio-gui_lchem_sweep/angio_lchem_sweep_combo003_omex_report.pdf) |
| **V-Cornea GUI** (decoupled pattern) | Surfactant dose `SLS_Concentration` = 250, 750, 2000 × 2 replicates (6 runs), 30 simulated days, chemical injury at day 3 | [experiment report](vcornea_sls_sweep/vcornea_sls_sweep_20261020_182006_experiment_report.pdf) | [SLS=250](vcornea_sls_sweep/vcornea_sls_sweep_combo001/vcornea_sls_sweep_combo001_omex_report.pdf) · [SLS=750](vcornea_sls_sweep/vcornea_sls_sweep_combo002/vcornea_sls_sweep_combo002_omex_report.pdf) · [SLS=2000](vcornea_sls_sweep/vcornea_sls_sweep_combo003/vcornea_sls_sweep_combo003_omex_report.pdf) |

The GUI writes all of these files automatically when a sweep finishes. The
reports are generated from the archives alone.

- **Experiment report.** Describes the scan archive (`*_scan.omex`), which ties
  the sweep together. It shows the SED-ML that encodes the scan, the provenance,
  the validation results, a summary-metrics table, and plots that overlay the
  combinations, one line per parameter value.
- **Combination report.** Covers one parameter value across its replicates. It
  shows each replicate archive's validation results, the provenance, the run
  identity (seed, schema fingerprint, code version), and the **parameter
  credibility** check, which compares each executed value with the ranges the
  schema documents. It also includes how to read the SED-ML, plots with each
  replicate and the replicate mean, and spatial snapshots (Angio-GUI).

Two results in the reports show what the audit trail is for:

- **Angio-GUI.** The lchem=1000 report flags *Chemotaxis Strength 1000 vs
  default 500: outside recommended range*. The run is valid, and the archive
  records that it left the documented range.
- **V-Cornea.** The SLS dose response is visible in the thickness plot. At
  SLS=2000, central epithelial thickness falls from about 40 µm to about 11 µm
  after the day-3 injury and recovers by about day 8. At 250 and 750 it barely
  changes.

## The archives

Each `.omex` file is a COMBINE archive, which is a zip file, so any unzip tool
can open it. Every run has its own archive in its replicate folder, and it
contains:

- `simulation.sedml`: the SED-ML simulation description.
- `run_metadata.json`: the resolved parameters and provenance.
- `parameter_audit.json`: every parameter checked against its schema.
- `environment.json` and `status.json`: the software environment and run outcome.
- `metadata.rdf`: OMEX metadata (creator, license, citation, code version).
- The logs, the model files, and the raw outputs. For Angio-GUI, this includes
  the full Zarr spatial trajectory.

The `*_scan.omex` archive at the top of each sweep holds the comparison SED-ML
and the per-combination data that the experiment report plots.

All 15 runs completed successfully. All archives record code `v1.0.3` (commit
`493b273`, clean build) and creator Joel Vanin. Every seed was drawn
independently at launch and recorded.

| | Angio-GUI | V-Cornea |
|---|---|---|
| Schema fingerprint | `sha256:0a6c2ceaca8b9cdf` | `sha256:d3c5ca23a40e24f9` |
| Run time per replicate | about 1 min | about 6.7 h |

The schema fingerprints match the parameter tables in the article's
supplementary material.

| Run | Run ID | Random seed |
|---|---|---|
| Angio-GUI lchem=100 rep 1 | `03106270e2924c57a7c60390d72be922` | 995172585 |
| Angio-GUI lchem=100 rep 2 | `d413766a286f42a1a2672069f2e53e5a` | 45372538 |
| Angio-GUI lchem=100 rep 3 | `a7d1ffb3803a4b55b46440cafcfa225c` | 1519009888 |
| Angio-GUI lchem=500 rep 1 | `262c441fc4224980a42682115e6aa094` | 1572808458 |
| Angio-GUI lchem=500 rep 2 | `f670664413de4f9d9600446cb3b20dc6` | 1963924785 |
| Angio-GUI lchem=500 rep 3 | `f3ace79014dc4f50ab7a1074996bcd56` | 2091564837 |
| Angio-GUI lchem=1000 rep 1 | `a6d59fdf0c0e41708f97d3c31f3157a4` | 1221895885 |
| Angio-GUI lchem=1000 rep 2 | `9ff5174acd9e4582ad9f268254b4586a` | 96861613 |
| Angio-GUI lchem=1000 rep 3 | `5686ea68e98b443d833eb269930ad0a8` | 635129125 |
| V-Cornea SLS=250 rep 1 | `70cfe7f5b4964bf0b630ba914286fcdf` | 1287481261 |
| V-Cornea SLS=250 rep 2 | `df07bf7d9d054748ad9d5214aa3abcbf` | 875085774 |
| V-Cornea SLS=750 rep 1 | `1888c583342241afb3909e5ac9a2ab8b` | 104329846 |
| V-Cornea SLS=750 rep 2 | `3ab88d96050046b4b32eb8469fb3ac5c` | 1022349946 |
| V-Cornea SLS=2000 rep 1 | `e4f33c9893ee41ee85a9297a2ac109af` | 479116128 |
| V-Cornea SLS=2000 rep 2 | `79bbb4eb0a374bbb90c2f991a326b537` | 1279642864 |

**Note on the Angio-GUI reports.** The v1.0.3 Angio-GUI report tool left the
parameter-credibility section out of its reports because of an import bug, fixed
in [#36](https://github.com/VaninJoel/schema-driven-interfaces/pull/36). The
Angio-GUI reports here were regenerated from the same v1.0.3 runs with the fixed
report tool, running in the v1.0.3 installed environment. The per-run archive
contents are byte-identical to what the sweep produced. The scan archive was
rebuilt, and only its creation timestamp changed.
