# Schema-Driven Interfaces

**Schema-driven graphical interfaces for agent-based biological models, wrapping
CompuCell3D (CC3D) simulations through [Vivarium](https://vivarium-collective.github.io/) processes.**

The unifying idea: a simulation is exposed as a Vivarium process whose
`ports_schema()` declares every parameter together with its type, units,
physiological range, and documentation. A PyQt5 GUI is then **generated from that
schema** — so the interface, validation, and in-app help stay in lockstep with the
model, and running an experiment never requires editing simulation code by hand.

---

## Components

| Folder | What it is |
|---|---|
| [`vcornea_paper`](vcornea_paper/) | The **V-Cornea** CompuCell3D model — an agent-based model of corneal epithelium homeostasis, injury, and recovery (Vanin et al. 2025, *PLOS Comput Biol* 21(12):e1013410). Includes the `Local/` and `HPC/` project layouts. |
| [`vivarium-vcornea`](vivarium-vcornea/) | A Vivarium process (`VCorneaProcess`) that wraps the V-Cornea model. Its schema is the single source of truth that drives the GUI. |
| [`vcornea-gui`](vcornea-gui/) | The **V-Cornea GUI** — a schema-driven PyQt5 application for configuring, running (batch sweeps / replicates), and analysing V-Cornea experiments. |
| [`vivarium-angio`](vivarium-angio/) | A Vivarium process wrapping an **angiogenesis** CC3D model. |
| [`angio-gui`](angio-gui/) | The schema-driven PyQt5 GUI for the angiogenesis model. |

The two GUIs share the same pattern; V-Cornea is the most fully developed example.

---

## Architecture

```
GUI (PyQt5)  →  Vivarium process (ports_schema)  →  CC3D subprocess
```

- Parameters are written into the model's `Parameters.py` at runtime.
- CC3D runs as a subprocess; outputs are captured as CSV/Parquet plus a
  `run_metadata.json` provenance record.
- The GUI's controls, range-checks, and info panels are all generated from the
  process schema.

---

## Installation

Everything runs in a single self-contained conda environment (`vc`) — one file
sets up CompuCell3D and the full Python stack:

```bash
conda env create -f environment.yml
conda activate vc
cd vcornea-gui && python run_gui.py     # or: cd angio-gui && python run_gui.py
```

See **[INSTALL.md](INSTALL.md)** for prerequisites, the angiogenesis GUI, display
(X11) notes, verification, and troubleshooting.

## Layout & dependencies

The folders are arranged so each GUI finds its sibling process package by relative
path (e.g. `vcornea-gui/run_gui.py` expects `../vivarium-vcornea`). Keep them as
siblings within this repository.

CompuCell3D is conda-only and is the engine behind every simulation; the
`environment.yml` installs it (4.7.0, Python 3.12) along with the analysis stack
and editable installs of the two wrapper packages. The analysis tools alone need
only the Python packages — no display or CC3D required to explore existing run
outputs.

---

## Status & scope

This is research software accompanying the V-Cornea paper. The models are intended
as mechanistic, hypothesis-generating tools rather than quantitative clinical
predictors. See each component's README for specifics.
