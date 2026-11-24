# Re-execution data

What the re-executions reported in [`../README.md`](../README.md#re-executing-the-examples)
produced, so the outputs can be compared with the archives without running
anything. All of it was made on 2026-11-24 in a fresh clone of this repository
with a conda environment newly built from `environment.yml` (named `sdi_clean`),
on the same Windows 11 machine that produced the examples. The clone was at
commit `49d9494` for every replay and for the first set of test logs.

| Folder | What was run | Result |
|---|---|---|
| `angio_combo002_rep01/` | Archive `angio_lchem_sweep_combo002_rep01.omex`, unpacked: `python -m cc3d.run_script -i model/angiogenesis.cc3d -o out` and `python model/run_model.py` | All 10 archived steps identical by both pathways. `array_checksums.csv` gives the SHA-256 of every array (archived, stock CompuCell3D, `run_model.py`); `comparison.txt` the largest difference per step (0 everywhere). The arrays themselves are not stored here: they equal the trajectory inside the archive |
| `vcornea_combo001_rep1_30day_replay/` | Archive `vcornea_sls_sweep_combo001.omex` (replicate 1), unpacked: `python -m cc3d.run_script -i model/vCornea_v2.cc3d -o out`, with `OPENBLAS_NUM_THREADS=1`; 7200 steps, 1 h 32 min | The three re-executed tables are here. `comparison.txt` (output of `vivarium-vcornea/compare_replay.py`): all rows identical. The two CSV files are byte-identical to the archived ones; the Parquet file is equal in content, not in bytes |
| `vcornea_one_day_run_and_replay/` | A one-day run (240 steps, no injury, seed 20261124) made through `VCorneaProcess` in the clean environment; its archive is here. The archive was unpacked and `model/vCornea_v2.cc3d` run with stock CompuCell3D, nothing edited | `replay_tables/` holds the re-executed tables; `comparison.txt`: all rows identical to the tables inside the archive |
| `vcornea_combo001_rep1_first_day_replay/` | The 30-day example archive again, with one line edited in `model/Simulation/Parameters.py`: `SimTime=7200` to `SimTime=240` (the edited file is here as `Parameters_edited.py`) | The tables of that day are here; `comparison.txt`: identical to the archived tables over the day they cover |
| `environment/` | `conda list --explicit`, `conda env export` and `pip freeze` of the environment, and the logs of `conda env create` (which fails in its pip step on Windows, as `INSTALL.md` describes) and of the `conda env update` that completes it | Python 3.12.2, CompuCell3D 4.7.0 |
| `test_logs/` | The three test suites in that environment: full logs at commit `49d9494` (113, 65 and 73 passed) and the result lines at commit `1ba4ee4` (124, 65 and 75 passed) | All passed |

To repeat a comparison, unpack the named archive and run the commands; for
V-Cornea then run `python vivarium-vcornea/compare_replay.py <unpacked archive>
<its model/Simulation> <final step>`.

Limits. Same machine and operating system as the original runs. One archive
per application. `OPENBLAS_NUM_THREADS=1` was set for the V-Cornea replays, as
the wrapper sets it for every run, and not for the Angio ones. The reason the
re-executed Parquet file differs in bytes while its contents are equal was not
investigated (pandas is 3.1.1 here and 3.0.6 where the archive was written).
The logs and the environment export contain local paths with the Windows user
name, as the run archives do.
