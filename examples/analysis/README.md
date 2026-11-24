# Analysis of the example runs

`angio_metric_study.py` computes, from the 30 Angio-GUI run archives alone,
shape and size measures that the application does not write to `metrics.csv`:
the number of cells, the mean cell area, the interior fraction of the cell mass
(the report's compactness) and others. They are the source of the mean cell area
row in [`../README.md`](../README.md) and of the statement that all 400 cells
are present in every run.

```bash
python examples/analysis/angio_metric_study.py            # rewrites the two tables
python examples/analysis/angio_metric_study.py --check    # compares with the stored tables
```

| File | Content |
|---|---|
| `angio_metric_study.csv` | one row per run and recorded step (30 runs x 10 steps) |
| `angio_metric_study_summary.csv` | final step, mean and SD over the 10 replicates of each chemotaxis strength |

Final step (100 Monte Carlo steps), mean over 10 replicates:

| | lchem = 100 | lchem = 500 | lchem = 1000 |
|---|---|---|---|
| Cells | 400 | 400 | 400 |
| Mean cell area (sites; target 50) | 45.3 | 35.6 | 27.1 |
| Interior fraction (compactness) | 0.70 | 0.47 | 0.33 |

The columns named `medium_components...` count connected regions of medium.
They are not vascular lacunae: in runs this short they are the gaps between
cells that are still aggregating. The column definitions are in the script's
docstring.
