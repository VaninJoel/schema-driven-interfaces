# Example runs

One parameter sweep for each case study, produced from a source checkout at
commit `210b9c3` (three commits after `v1.0.4`, clean working tree) by
operating the real GUI on Qt's off-screen platform:

```
python examples/run_example_sweep.py angio   <out_dir> --name angio_lchem_sweep \
    --operator "Joel Vanin" --replicates 10 lchem="100, 500, 1000"
python examples/run_example_sweep.py vcornea <out_dir> --name vcornea_sls_sweep \
    --operator "Joel Vanin" --replicates 5 --max-runs 3 SLS_Concentration="1500, 2000, 2500"
```

The script does what a user does: it enters an experiment name and the operator
name, types a comma-separated list of values into one parameter field, sets the
number of replicates and presses **Run Simulation**. The window, validation,
worker, archives and reports are the application's own code; only the clicks are
scripted, so the runs can be regenerated unattended. Every other parameter
stayed at its schema default. These runs were not made with a packaged
installer.

| Case study | Sweep | Experiment report (start here) | Per-combination reports |
|---|---|---|---|
| **Angio-GUI** (integrated pattern) | Chemotaxis strength `lchem` = 100, 500, 1000 × 10 replicates (30 runs), 100 Monte Carlo steps | [experiment report](angio-gui_lchem_sweep/angio_lchem_sweep_20261123_184815_experiment_report.pdf) | [lchem=100](angio-gui_lchem_sweep/angio_lchem_sweep_combo001_omex_report.pdf) · [lchem=500](angio-gui_lchem_sweep/angio_lchem_sweep_combo002_omex_report.pdf) · [lchem=1000](angio-gui_lchem_sweep/angio_lchem_sweep_combo003_omex_report.pdf) |
| **V-Cornea GUI** (decoupled pattern) | Surfactant dose `SLS_Concentration` = 1500, 2000, 2500 × 5 replicates (15 runs), 30 simulated days, chemical injury at day 3 | [experiment report](vcornea_sls_sweep/vcornea_sls_sweep_20261123_184813_experiment_report.pdf) | [SLS=1500](vcornea_sls_sweep/vcornea_sls_sweep_combo001/vcornea_sls_sweep_combo001_omex_report.pdf) · [SLS=2000](vcornea_sls_sweep/vcornea_sls_sweep_combo002/vcornea_sls_sweep_combo002_omex_report.pdf) · [SLS=2500](vcornea_sls_sweep/vcornea_sls_sweep_combo003/vcornea_sls_sweep_combo003_omex_report.pdf) |

The GUI writes all of these files automatically when a sweep finishes. The
reports are generated from the archives alone, and they are exactly the files
the application wrote; nothing was regenerated afterwards.

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
  schema documents and names the basis of each range. It also explains how to
  read the SED-ML, and includes plots of each replicate and the replicate mean,
  and spatial snapshots (Angio-GUI).

The validation result in a report says that the archive is well-formed and
exchangeable. The validator has no checker for CompuCell3D model files, so it
does not check the model or its results.

## What the examples show, and what they do not

These sweeps demonstrate the workflow: one field edited, replicates run,
everything recorded, reports built from the archives. They are not new
biological results.

- **Angio-GUI.** This is a short run (100 Monte Carlo steps) that captures
  early aggregation, not a developed vascular network.

  | Final step, mean ± SD (n = 10) | lchem = 100 | lchem = 500 | lchem = 1000 | Kruskal–Wallis p |
  |---|---|---|---|---|
  | Clusters | 1.0 ± 0 | 1.0 ± 0 | 1.2 ± 0.4 | 0.126 |
  | Largest cluster (sites) | 18,122 ± 25 | 14,234 ± 64 | 10,820 ± 101 | 2.5e-6 |
  | Cell density (fraction of lattice) | 0.453 ± 0.001 | 0.356 ± 0.002 | 0.271 ± 0.003 | 2.5e-6 |
  | Mean cell area (sites; target 50) | 45.3 | 35.6 | 27.1 | — |
  | Mean VEGF | 1.98 ± 0.02 | 1.01 ± 0.01 | 0.616 ± 0.007 | 2.5e-6 |

  How to read it. The cells form essentially one connected cluster at every
  chemotaxis strength, so the cluster count does not separate the conditions; in
  an earlier sweep with other seeds it happened to (p = 0.012), which shows that
  it depends on the seeds at this run length. All 400 cells are present in every
  run, so cell density is the mean cell area times 400 divided by the 40,000
  lattice sites: density and largest-cluster size fall with chemotaxis strength
  because the cells are compressed (to about 54% of their target area at
  lchem = 1000), not because the network has a different shape. Mean cell area
  was computed from the archived trajectories; the application does not write it
  to `metrics.csv`; the script and its per-run table are in
  [`analysis/`](analysis/). The lchem = 1000 runs carry the recorded note *outside the
  recommended range [100, 800] (range set by exploratory presets)*: the runs are
  valid, and each archive records that the value left the documented range.
  Metrics are computed on a lattice that is periodic in both directions, and the
  `metrics.csv` in each of the 30 archives was checked against a recomputation
  from the archived trajectory (30 of 30 match).

  The implementation follows the mechanism of Merks et al. 2008 but not its
  parameter values (the schema states the differences entry by entry), so these
  numbers are not comparable with that paper's.

- **V-Cornea.** The surfactant dose sets how deep the injury goes and how long
  the tissue takes to recover.

  | Mean ± SD (n = 5) | SLS = 1500 | SLS = 2000 | SLS = 2500 | Kruskal–Wallis p |
  |---|---|---|---|---|
  | Central thickness before injury (µm) | 38.5 ± 0.4 | 38.6 ± 0.8 | 39.3 ± 0.2 | 0.030 |
  | Central thickness, minimum after injury (µm) | 27.0 ± 0.5 | 21.1 ± 0.7 | 18.6 ± 1.3 | 0.002 |
  | Days to recover 90% of pre-injury thickness | 1.6 ± 0.2 | 2.7 ± 0.4 | 4.9 ± 1.2 | 0.002 |
  | Central thickness at day 30 (µm) | 41.4 ± 0.8 | 42.3 ± 1.8 | 36.4 ± 1.0 | 0.008 |
  | Wing cells, minimum after injury | 92.4 ± 2.3 | 80.6 ± 3.4 | 75.6 ± 2.9 | 0.003 |
  | Surfactant clearance half-life (h) | 29.9 ± 0.2 | 33.5 ± 0.6 | 37.2 ± 0.2 | 0.002 |

  With five replicates per value the tests have little power and are not
  corrected for the number of endpoints; read them as descriptive. The small
  pre-injury difference (p = 0.030) arises before the dose can act, so it is
  replicate-to-replicate variation.

## The archives

Each `.omex` file is a COMBINE archive, which is a zip file, so any unzip tool
can open it. Every run has its own archive in its replicate folder, and it
contains:

- `simulation.sedml`: the SED-ML simulation description.
- `run_metadata.json`: the resolved parameters, the specification check, the
  seed and what it was applied to, and the provenance.
- `parameter_audit.json`: every parameter checked against its schema.
- `environment.json` and `status.json`: the software environment and run outcome.
- `metadata.rdf`: OMEX metadata (creator, license, citation, code version).
- The logs, the model files, and the raw outputs. For Angio-GUI, this includes
  the full Zarr spatial trajectory and `metrics.csv`.

The `*_scan.omex` archive at the top of each sweep holds the comparison SED-ML
and the per-combination data that the experiment report plots.

All 45 runs completed successfully. All archives record commit `210b9c3`
(`v1.0.4-3-g210b9c3`, branch `fix/reviewer-code-findings`, no uncommitted
changes) and creator Joel Vanin. Every seed was drawn independently at launch
and recorded, and all 45 seeds are different. In V-Cornea the seed is applied to
both CompuCell3D's generator and Python's, and each archive records that both
were set.

| | Angio-GUI | V-Cornea |
|---|---|---|
| Schema fingerprint | `sha256:7962f735412f08c2` | `sha256:d3c5ca23a40e24f9` |
| Run time per replicate | 89–150 s | about 5.3 h (15 runs in parallel) |

The schema fingerprints match the parameter tables in `docs/supplementary/`.

**What a seed reproduces.** Running the same parameters with the same seed on
the same machine and software reproduces the stored outputs exactly
(`tests/test_angio_reexecution.py`, `tests/test_vcornea_reexecution.py`). A seed
does not carry over between different parameter values: CompuCell3D draws all
its random numbers from one stream, so changing a parameter changes which draw
is used where.

## Re-executing the examples

Each archive carries the model it ran under `model/`, so it can be run again
without the GUI. The table gives, for one archive of each application, the
commands, the environment, what is expected and what was observed. The
observations were made on 2026-11-24 in a fresh clone of this repository
(commit `49d9494`) with a new conda environment created from `environment.yml`
under another name (`conda env create -n sdi_clean -f environment.yml`, conda
26.7.2, Windows 11). That command installed the conda packages and then failed
in its pip step (exit code 1) with the Windows error `INSTALL.md` describes
(`vs2015_compiler_vars.bat`); after the documented workaround, deleting that
file and running `conda env update -n sdi_clean -f environment.yml`, the
environment was complete. Both commands together took about 39 minutes with
the machine's existing package cache. No terms-of-service prompt appeared for
Anaconda's `defaults` channel, and this conda has no `conda tos` command. The
environment resolved to Python 3.12.2, CompuCell3D 4.7.0, NumPy 2.2.6, pandas
3.1.1 (the example archives were written with 3.0.6), Zarr 3.4.2, PyArrow
18.1.0, vivarium-core 1.6.5 and biosimulators-utils 0.2.3. This is the same
machine and operating system as the original runs; no other machine was tried,
and one archive per application was re-executed.

| | Angio-GUI | V-Cornea |
|---|---|---|
| Archive | `angio-gui_lchem_sweep/angio_lchem_sweep_combo002_rep01/angio_lchem_sweep_combo002_rep01.omex` (lchem = 500, seed 462244942) | `vcornea_sls_sweep/vcornea_sls_sweep_combo001/replicate_1/vcornea_sls_sweep_combo001.omex` (SLS = 1500, seed 2043774806) |
| Commands, in the unpacked archive | `python -m cc3d.run_script -i model/angiogenesis.cc3d -o out` and `python model/run_model.py` | `python -m cc3d.run_script -i model/vCornea_v2.cc3d -o out`, then `python vivarium-vcornea/compare_replay.py . model/Simulation <final step>` |
| Expected output | `model/native_output/step_<MCS>.npy` and `model/rerun_output/data.zarr`: every archived step (10, 20, …, 100) equal to the archived trajectory | `model/Simulation/cell_count_<N>.csv`, `surfactant_<N>.csv`, `thickness_rep_<N>.parquet`: every row equal to the archived tables |
| Observed, full run | Both commands: all 10 archived steps identical (200 × 200 lattice, 3 fields). Each took one to two minutes | 30-day replay of the example archive (7200 steps, with `OPENBLAS_NUM_THREADS=1` as the wrapper sets it): all three tables equal to the archived ones in every value (721 cell-count rows, 7201 surfactant rows, 7210 thickness rows). The two CSV files are also byte-identical; the Parquet file's bytes differ while its contents are equal (not investigated; the pandas version differs). Run time 1 h 32 min |
| Observed, brief run | not needed: the full run is brief | (1) A one-day run (240 steps, no injury, seed 20261124) was produced in that environment through the wrapper (`VCorneaProcess`, 3.5 minutes), its archive unpacked, and `model/vCornea_v2.cc3d` run with stock CompuCell3D, nothing edited: all three tables identical to the archived ones (25 cell-count rows, 241 surfactant rows, 250 thickness rows). (2) The example archive above with `SimTime` lowered to 240 steps in `model/Simulation/Parameters.py`: all three tables identical to the archived ones over that day (same row counts). Each replay took 3 to 6 minutes |
| Test suites in that environment | `pytest tests`: 124 passed; `pytest vivarium-angio`: 65 passed | `pytest vivarium-vcornea`: 75 passed |

The test suites were run in the same clone and environment after updating the clone to commit `1ba4ee4`; the archive replays were run at `49d9494`. How a replay and the comparison
are run is described in [`vivarium-angio/README.md`](../vivarium-angio/README.md)
and [`vivarium-vcornea/README.md`](../vivarium-vcornea/README.md#re-executing-from-the-unpacked-archive).
The outputs of these re-executions (tables, checksums, comparison results,
the environment's package list and the test logs) are in
[`reexecution/`](reexecution/).

<details>
<summary>Run IDs and random seeds of all 45 runs</summary>

| Run | Run ID | Random seed |
|---|---|---|
| Angio-GUI lchem=100 rep 1 | `66dc78a6ccd14bab80ff750b58639733` | 198185322 |
| Angio-GUI lchem=100 rep 2 | `df7631697cb44d05858785144f2da5e9` | 1738344046 |
| Angio-GUI lchem=100 rep 3 | `df33a1edcf85448780cc37de32a65159` | 2045929536 |
| Angio-GUI lchem=100 rep 4 | `45dd0f0146a040bf86dc5dfd640ff139` | 1535784999 |
| Angio-GUI lchem=100 rep 5 | `331d27fa4dfc4db18b4a78ee615a0a38` | 1786945182 |
| Angio-GUI lchem=100 rep 6 | `551e8e9fdf43488fb787e7d135eea55b` | 371364970 |
| Angio-GUI lchem=100 rep 7 | `c572d95d47cf48d8a96ef74870aae805` | 349887123 |
| Angio-GUI lchem=100 rep 8 | `a19808d63d024c2b91f1970c56379996` | 391713927 |
| Angio-GUI lchem=100 rep 9 | `353db13cc3064a3d898ef959c0204eaf` | 1235584987 |
| Angio-GUI lchem=100 rep 10 | `c008c73f61ea45298ba288e5ba1d3d0a` | 1110026456 |
| Angio-GUI lchem=500 rep 1 | `33a78546b2f0495794ceee2e31a6430c` | 462244942 |
| Angio-GUI lchem=500 rep 2 | `08c1108128d24b498df146a846060e5a` | 1850415588 |
| Angio-GUI lchem=500 rep 3 | `066944b04135404aa81bd5dd566004e3` | 1518811918 |
| Angio-GUI lchem=500 rep 4 | `4856099e79b5478c9008b2c0a5a96019` | 2015512825 |
| Angio-GUI lchem=500 rep 5 | `880ba7046fda462187c34ed017ada63a` | 1455510720 |
| Angio-GUI lchem=500 rep 6 | `2465cb6fedcd44888441422d594bcaee` | 585018796 |
| Angio-GUI lchem=500 rep 7 | `e646eec367ff4ddc9185378437dc17d6` | 738229051 |
| Angio-GUI lchem=500 rep 8 | `97b4e9c31b484bcb8e518d33d0fdf0cd` | 2041809786 |
| Angio-GUI lchem=500 rep 9 | `072d8d32249c471b906cd939f33039bd` | 201218724 |
| Angio-GUI lchem=500 rep 10 | `addc94a542a1467eaeef8715c5ecff05` | 429744752 |
| Angio-GUI lchem=1000 rep 1 | `3e04559594bb4e23bef148ae3b4027e0` | 1698691488 |
| Angio-GUI lchem=1000 rep 2 | `48a6b2a2882d435fb844b54494d856c0` | 1213542268 |
| Angio-GUI lchem=1000 rep 3 | `42cdd5f0c6a247e7971adaaea1877528` | 775013793 |
| Angio-GUI lchem=1000 rep 4 | `7757dd79ab61443197ea86dcef1d5961` | 90479371 |
| Angio-GUI lchem=1000 rep 5 | `3444bae088e64b9e9d3d29672f8ef586` | 514314119 |
| Angio-GUI lchem=1000 rep 6 | `556f85be01774e118bd6ec96c3280550` | 1354610026 |
| Angio-GUI lchem=1000 rep 7 | `165eac7c9f6a47d58ee02001cf78e7d3` | 1916571327 |
| Angio-GUI lchem=1000 rep 8 | `f6ca22ea09694b9ca0e31d7e6b249654` | 212264974 |
| Angio-GUI lchem=1000 rep 9 | `c9aac0e1fd104d458fa3294db6275572` | 628337203 |
| Angio-GUI lchem=1000 rep 10 | `eeccbd81b3024a548247f4ec4b7c7f2e` | 1249975569 |
| V-Cornea SLS=1500 rep 1 | `80b7ca7516004448860b0b08dace29ae` | 2043774806 |
| V-Cornea SLS=1500 rep 2 | `13898d7e69df416784e43ad5df4d5a88` | 2038607285 |
| V-Cornea SLS=1500 rep 3 | `42011ef91a7d4b7197480efb37b5060f` | 1174182372 |
| V-Cornea SLS=1500 rep 4 | `ebd4fdbc47674b2ebf334c9a13d6bbab` | 1040383161 |
| V-Cornea SLS=1500 rep 5 | `94b986abf9864a558aa7043082af4942` | 1871028149 |
| V-Cornea SLS=2000 rep 1 | `d3f6538dd563483d859253d0a267cec1` | 170115583 |
| V-Cornea SLS=2000 rep 2 | `df016b6ca51348e29f64706557d81453` | 776236506 |
| V-Cornea SLS=2000 rep 3 | `669e6187a8ed4b49a3feedfc87ee78bb` | 1771680398 |
| V-Cornea SLS=2000 rep 4 | `b97685ca77ae4bb6809bab20af899e5e` | 596989275 |
| V-Cornea SLS=2000 rep 5 | `6334f32f5edd4b5aa284ef478937591a` | 1168364392 |
| V-Cornea SLS=2500 rep 1 | `a0514312feab4bf09899c4b091111c1a` | 941519068 |
| V-Cornea SLS=2500 rep 2 | `79b8139ac75f47c795f28b1b2fea4f2e` | 283269580 |
| V-Cornea SLS=2500 rep 3 | `02a7971b24c244f1815d1ba8f60f2f40` | 486386432 |
| V-Cornea SLS=2500 rep 4 | `957686f9618a46c7bf8cf4a96cb6b861` | 2007765686 |
| V-Cornea SLS=2500 rep 5 | `6adc0120a502459f82afbe57424302c1` | 344686615 |

</details>
