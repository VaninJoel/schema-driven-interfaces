# vCornea CellFate GUI: A Standalone Application for Corneal Cell Fate Simulations

**Accessible, reproducible workflows for vCornea CellFate simulations**

---

## Overview

**vCornea CellFate GUI** is a standalone application that packages the vCornea cell fate CompuCell3D (CC3D) model into a schema-driven GUI. It enables injury-response and cell-fate experiments without requiring direct CC3D scripting.

Key strengths:
- Schema-driven parameter controls with rich documentation
- Batch runs, parameter sweeps, and replicates
- Reproducible output organization with metadata
- Analysis window for post-run visualization

---

## Architecture

This GUI follows a **decoupled, black-box wrapper** approach:

```
GUI (PyQt5) → Vivarium process (VCorneaProcess) → CC3D subprocess
```

- Parameters are written into `Simulation/Parameters.py` at runtime.
- CC3D runs as a subprocess (no live plotting).
- Outputs are captured as CSV/Parquet files plus `run_metadata.json`.

---

## Key Features

- **Schema-Driven UI**: Controls generated from `VCorneaProcess.ports_schema()`
- **Expertise Levels**: Basic, Intermediate, Advanced parameter visibility
- **Batch Execution**: Parameter sweeps and replicates
- **Validation**: Physiological range checks with inline feedback
- **Metadata Capture**: Full parameter and run provenance

---

## Outputs

Each run writes outputs to a dedicated folder:

```
experiment_name/
├── cell_count_*.csv
├── thickness_rep*_*.parquet
├── surfactant_*.csv
├── logs/
│   ├── stdout.log
│   └── stderr.log
└── run_metadata.json
```

For batch runs (parameter sweeps / replicates) these files live under
`experiment_name/<combo>/replicate_*/` subfolders.

---

## Requirements

- Python 3.10+
- Python packages: `PyQt5`, `numpy`, `pandas`, `matplotlib`, `scipy`, `seaborn`, `pyarrow`
  (install with `pip install -r requirements.txt`)
- **CompuCell3D** (CC3D) installed and importable — required to run simulations.
- The **`vivarium-vcornea`** package, expected as a sibling folder next to this
  repository (`../vivarium-vcornea`). `run_gui.py` adds it to the path automatically
  if present. It provides `VCorneaProcess`, whose schema drives the GUI.

> The Analyze Results window only needs the Python packages above — you can explore
> existing run outputs without a CC3D installation.

---

## Quick Start

```bash
python run_gui.py
```

1. Select an output directory.
2. Adjust parameters or pick a preset.
3. Click **Run Simulation**.
4. Open **Analyze Results** to inspect outputs.

---

## Notes

- Live plotting is not enabled in the black-box workflow.
- Use parameter sweeps with comma-separated values.
- CC3D installation is required for simulation execution.

---

**Last Updated:** June 2026
