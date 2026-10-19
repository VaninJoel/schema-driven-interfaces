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

## Installation

- **No coding:** download the desktop installer for your OS from the
  [repository README](../README.md).
- **From source:** follow [INSTALL.md](../INSTALL.md) — one conda environment
  (`vc`) provides CompuCell3D 4.7.0, Python 3.12, PyQt5 and the sibling
  `vivarium-vcornea` package, whose `VCorneaProcess` schema drives this GUI.

> The Analyze Results window only needs the Python packages — you can explore
> existing run outputs without a CompuCell3D installation.

---

## Quick Start

```bash
conda activate vc
cd vcornea-gui
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
- Every parameter's meaning, units, ranges and evidence: click its ⓘ button, or see
  Supplementary Table S2 of the paper.
- CC3D installation is required for simulation execution.

---

See the [repository README](../README.md#how-to-cite) for citation and license (MIT).
