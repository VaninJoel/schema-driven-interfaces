# vivarium-vcornea examples

Scripts that drive `VCorneaProcess` directly from Python, without the GUI. Run
them from the repository root with the `vc` environment active
(see [INSTALL.md](../../INSTALL.md)).

| Script | What it does |
|---|---|
| `run_vcornea_test.py` | One short injury simulation (100 MCS) — the quickest check that CompuCell3D runs through the process. |
| `injury_comparison_study.py` | Runs several injury scenarios and compares their outcomes. |
| `parameter_sweep_example.py` | A small parameter sweep with replicates. |

```bash
python vivarium-vcornea/experiments/run_vcornea_test.py
```

The CC3D project in [`vcornea_paper/`](../../vcornea_paper/) is located
automatically. Outputs are written under the process's output directory, one folder
per replicate, each with its logs, `run_metadata.json` and OMEX archive.

Parameter names, units and supported ranges are listed in
Supplementary Table S2 of the paper.
