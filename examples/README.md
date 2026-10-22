# Example runs

One parameter sweep for each case study, run with the released **v1.0.3**
Windows installer the way a user would:
1. Open the app and enter an experiment name and the operator name.
2. Type a comma-separated list of values into one parameter field.
3. Set the number of replicates and press **Run Simulation**.

Every other parameter stayed at its schema default.

| Case study | Sweep | Experiment report (start here) | Per-combination reports |
|---|---|---|---|
| **Angio-GUI** (integrated pattern) | Chemotaxis strength `lchem` = 100, 500, 1000 × 10 replicates (30 runs) | [experiment report](angio-gui_lchem_sweep/angio_lchem_sweep_20261021_114558_experiment_report.pdf) | [lchem=100](angio-gui_lchem_sweep/angio_lchem_sweep_combo001_omex_report.pdf) · [lchem=500](angio-gui_lchem_sweep/angio_lchem_sweep_combo002_omex_report.pdf) · [lchem=1000](angio-gui_lchem_sweep/angio_lchem_sweep_combo003_omex_report.pdf) |
| **V-Cornea GUI** (decoupled pattern) | Surfactant dose `SLS_Concentration` = 1500, 2000, 2500 × 5 replicates (15 runs), 30 simulated days, chemical injury at day 3 | [experiment report](vcornea_sls_sweep/vcornea_sls_sweep_20261021_115344_experiment_report.pdf) | [SLS=1500](vcornea_sls_sweep/vcornea_sls_sweep_combo001/vcornea_sls_sweep_combo001_omex_report.pdf) · [SLS=2000](vcornea_sls_sweep/vcornea_sls_sweep_combo002/vcornea_sls_sweep_combo002_omex_report.pdf) · [SLS=2500](vcornea_sls_sweep/vcornea_sls_sweep_combo003/vcornea_sls_sweep_combo003_omex_report.pdf) |

The GUI writes all of these files automatically when a sweep finishes. The
reports are generated from the archives alone.

- **Experiment report.** Describes the scan archive (`*_scan.omex`), which ties
  the sweep together. It shows the SED-ML that encodes the scan, the provenance
  and the validation results. Its **summary statistics** table computes each
  endpoint for every replicate separately, then gives mean ± SD and the 95%
  confidence interval of the mean for each parameter value, with a
  Kruskal–Wallis test across the values. A dot plot shows every replicate.
  Time-course plots overlay the combinations, one line per parameter value, with
  a ±1 SD band across replicates. The V-Cornea report also includes the GUI's
  paper-style tissue thickness figure for each value.
- **Combination report.** Covers one parameter value across its replicates. It
  shows each replicate archive's validation results, the provenance, the run
  identity (seed, schema fingerprint, code version), and the **parameter
  credibility** check, which compares each executed value with the ranges the
  schema documents. It also explains how to read the SED-ML, and includes plots
  of each replicate and the replicate mean, and spatial snapshots (Angio-GUI).

What the reports show:

- **Angio-GUI.** The lchem=1000 report flags *Chemotaxis Strength 1000 vs
  default 500: outside recommended range*. The run is valid, and the archive
  records that it left the documented range. As chemotaxis strength rises from
  100 to 1000, the final network breaks into more clusters (4.6 ± 1.0 → 8.5 ±
  2.7) and the largest cluster shrinks (17,914 ± 211 → 10,477 ± 161 pixels).
  Both differences are significant (Kruskal–Wallis p ≤ 0.001, n = 10 per value).
- **V-Cornea.** The surfactant dose sets how deep the injury goes and how long
  the tissue takes to recover. Central epithelial thickness before injury is
  about 38.5 µm at all three doses. After the day-3 injury it falls to 27.5 ±
  1.6 µm (SLS 1500), 21.2 ± 1.5 µm (2000) and 16.7 ± 0.2 µm (2500), and it
  recovers to 90% of its pre-injury value in 1.5, 2.7 and 5.4 days. At SLS 2500
  the tissue is still thinner at day 30 (35.1 ± 2.6 µm against 43.0 µm at 1500).
  The surfactant clearance half-life increases from 29.7 to 37.9 h. All
  Kruskal–Wallis p ≤ 0.006, n = 5 per value.

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

All 45 runs completed successfully. All archives record code `v1.0.3` (commit
`493b273`, clean build) and creator Joel Vanin. Every seed was drawn
independently at launch and recorded, and all 45 seeds are different.

| | Angio-GUI | V-Cornea |
|---|---|---|
| Schema fingerprint | `sha256:0a6c2ceaca8b9cdf` | `sha256:d3c5ca23a40e24f9` |
| Run time per replicate | 80–138 s | about 6.7 h (15 runs in parallel) |

The schema fingerprints match the parameter tables in the article's
supplementary material.

<details>
<summary>Run IDs and random seeds of all 45 runs</summary>

| Run | Run ID | Random seed |
|---|---|---|
| Angio-GUI lchem=100 rep 1 | `4e3556aed1134530a475f0db137aae63` | 1186538411 |
| Angio-GUI lchem=100 rep 2 | `e686353c5307497aba8cb3f5c10ce029` | 1591706957 |
| Angio-GUI lchem=100 rep 3 | `502f984b2c0745e09385cd9d3671b806` | 1517375581 |
| Angio-GUI lchem=100 rep 4 | `457a4d3cc8084f47b41407a0ed138a11` | 917905212 |
| Angio-GUI lchem=100 rep 5 | `ff849d5eca2e428592c09ecd8b86014e` | 1497126697 |
| Angio-GUI lchem=100 rep 6 | `b4d0406998ba45cd961aefb3424463bd` | 1769884084 |
| Angio-GUI lchem=100 rep 7 | `f65cb42a9f4a43f68cecedee2fde9f89` | 515536928 |
| Angio-GUI lchem=100 rep 8 | `675a59d9d56041b99985916230a701cc` | 63575998 |
| Angio-GUI lchem=100 rep 9 | `9b9f6741dcc841bfb1dac600765c7302` | 579214122 |
| Angio-GUI lchem=100 rep 10 | `adf9085876bc4575a25be15a67047057` | 2061748046 |
| Angio-GUI lchem=500 rep 1 | `8b03118627204e82a33212fdcf7b3ce9` | 525065339 |
| Angio-GUI lchem=500 rep 2 | `49ece175fef4486b93852ca497ba24ec` | 390316502 |
| Angio-GUI lchem=500 rep 3 | `a7843462f1f643938d75a010f6600652` | 1687630425 |
| Angio-GUI lchem=500 rep 4 | `ef51bc69968c49ffb6cc3b37a8a85680` | 235136279 |
| Angio-GUI lchem=500 rep 5 | `27cfcb86d2da4a368700c020b269b601` | 921580233 |
| Angio-GUI lchem=500 rep 6 | `badcb27e35c644df8ffeb0e990c94434` | 1606206427 |
| Angio-GUI lchem=500 rep 7 | `77224f48e2ec4f03b3ccd9832ca8a4d4` | 185941731 |
| Angio-GUI lchem=500 rep 8 | `47e086f2a9d249ee9df6b03c34acf941` | 2047667093 |
| Angio-GUI lchem=500 rep 9 | `627bbe7ac48f4ff6a663b50b9e3b2dfd` | 2033775562 |
| Angio-GUI lchem=500 rep 10 | `0dc75b73446742c193722b9e813ff904` | 1048620580 |
| Angio-GUI lchem=1000 rep 1 | `958b2e6d4ee94a4f8a73e600478928b8` | 660225677 |
| Angio-GUI lchem=1000 rep 2 | `3105cf20919b4d8ca4d40394c86079f0` | 55186854 |
| Angio-GUI lchem=1000 rep 3 | `e17f4e02ca9a41a68ddbbb6876beaae5` | 1906219765 |
| Angio-GUI lchem=1000 rep 4 | `79cdfe328af34472a51f51c03be9dd5a` | 1192207936 |
| Angio-GUI lchem=1000 rep 5 | `d1bd2c05fb6242fd86f03d1f2b2a4a81` | 1735493633 |
| Angio-GUI lchem=1000 rep 6 | `6d83688b8f7c4d8e85726808eae4823d` | 1982439393 |
| Angio-GUI lchem=1000 rep 7 | `e8f01971b76e4fdaa3cc03e35a199ff1` | 146488917 |
| Angio-GUI lchem=1000 rep 8 | `756e14166c584bc4aca597e876d0360f` | 910317449 |
| Angio-GUI lchem=1000 rep 9 | `b1f8bb83a14c445a8959396c4daf23ab` | 1851522618 |
| Angio-GUI lchem=1000 rep 10 | `ad92b3a6e412449baeb8b18851aa764b` | 431623095 |
| V-Cornea SLS=1500 rep 1 | `26ca72ae54e741c58d829ff45d61e11c` | 310740925 |
| V-Cornea SLS=1500 rep 2 | `9c8c7a5d4ff04eb9883665864ae7811f` | 477597378 |
| V-Cornea SLS=1500 rep 3 | `ccb76777c46c4d4f99658235566f304a` | 614363402 |
| V-Cornea SLS=1500 rep 4 | `4e1007ad835e44f4874d5e07d394d486` | 611214328 |
| V-Cornea SLS=1500 rep 5 | `e2659bc5cf1e4ba2a1a278ebbd4063c5` | 1929517918 |
| V-Cornea SLS=2000 rep 1 | `7bca68a07c7444eba99e9c3d9fb9f08a` | 1574844843 |
| V-Cornea SLS=2000 rep 2 | `2028ccd8b559498d85fcc72ddcc9b14a` | 643665948 |
| V-Cornea SLS=2000 rep 3 | `6229522dec944298ac2439500dad24e9` | 1797272279 |
| V-Cornea SLS=2000 rep 4 | `840970cc33204cfeb5852e16ff83e765` | 321534142 |
| V-Cornea SLS=2000 rep 5 | `4b621090bf1c458f9f82907bceb034c0` | 346823061 |
| V-Cornea SLS=2500 rep 1 | `05d5f7919c214a27ad1ae86703cd9107` | 2038141807 |
| V-Cornea SLS=2500 rep 2 | `16e8927d8ff345a3979fee655dc4804c` | 1634574597 |
| V-Cornea SLS=2500 rep 3 | `1eec93e565c547b6a6cfd6ec2678b952` | 1865787388 |
| V-Cornea SLS=2500 rep 4 | `1c514e66ca0745bba0800fbd92862d24` | 1573581721 |
| V-Cornea SLS=2500 rep 5 | `c81046e0a13c41ebb5c4ab891ba0eedf` | 546445566 |

</details>

**Note on the reports.** The runs and their archives are exactly what the v1.0.3
installer produced. The PDF reports were then regenerated from those archives
with the improved report tools of
[#36](https://github.com/VaninJoel/schema-driven-interfaces/pull/36) and
[#38](https://github.com/VaninJoel/schema-driven-interfaces/pull/38), running in
the v1.0.3 installed environment. These tools add the per-replicate statistics,
the parameter-credibility section in the Angio-GUI reports, and the paper-style
thickness figure. They also count an X-bin with no epithelium left as zero
thickness rather than a negative value. Version 1.0.4 and later write these
reports directly. Regenerating left every per-run archive byte-identical. The
Angio-GUI scan archive was rebuilt, and only its creation timestamp changed. The
V-Cornea report tool only reads the archives.
