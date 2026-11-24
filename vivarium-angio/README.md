# Vivarium-Angio: Integrated Architecture for CompuCell3D Angiogenesis Simulations

A demonstration of the **Integrated Architecture** pattern for wrapping CompuCell3D (CC3D) simulations within the Vivarium multiscale modeling framework, using an angiogenesis model as a case study.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Running Simulations](#running-simulations)
- [Reading a trajectory](#reading-a-trajectory)
- [The archive](#the-archive)
- [Architecture Comparison](#architecture-comparison)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)
- [Citation](#citation)

---

## Overview

This project demonstrates how to integrate CompuCell3D simulations into Vivarium using the **Integrated Architecture** approach, which provides:

- **Runtime control** - Fine-grained control via programmable `step()` methods
- **Incremental data availability** - Data written to Zarr store during execution, not just at completion
- **Stepwise execution** - The process advances the model one Monte Carlo step per update, so intermediate state is observable and output timing is decided outside the model rules
- **One store per run** - Each run writes its own Zarr hierarchy, with its parameters stored as attributes of the trajectory
- **Cloud-ready** - Zarr format optimized for distributed/cloud computing

### Biological Model

The angiogenesis model simulates endothelial cell (EC) migration and VEGF (Vascular Endothelial Growth Factor) dynamics:

- **Cells**: Endothelial cells (EC) that adhere, migrate, and secrete VEGF
- **Chemical field**: VEGF diffuses and guides cell chemotaxis
- **Parameters**: Cell-cell adhesion (`jee`), cell-medium adhesion (`jem`), chemotaxis strength (`lchem`), VEGF diffusion/decay/secretion rates

---

## Architecture

### Integrated Architecture Pattern

```
┌─────────────────────────────────────────────────────────┐
│                 Vivarium Engine                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │       AngiogenesisProcess (Vivarium Process)      │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │     CC3DSimService (API-driven)             │  │  │
│  │  │  • Direct in-process control                │  │  │
│  │  │  • step() / step_write() commands           │  │  │
│  │  │  • WriterSteppable with task awareness      │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  │                      ↓                            │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │     StoreManager (Zarr I/O)                 │  │  │
│  │  │  • Incremental writes every 10 steps        │  │  │
│  │  │  • Parameters as metadata                   │  │  │
│  │  │  • Unified hierarchical storage             │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          ↓
               <run directory>/data.zarr/        one store per run
               ├── (attributes: exp_name, params)
               ├── 10/data
               ├── 20/data
               └── ...
```

### Key Components

1. **AngiogenesisProcess** (`vivarium_angio/processes/angiogenesis_process.py`)
   - Vivarium Process wrapping CC3D simulation
   - Implements `next_update()` for step-by-step execution
   - Manages CC3DSimService lifecycle

2. **WriterSteppable** (within `angiogenesis_process.py`)
   - CC3D Steppable with task-aware behavior
   - Responds to 'write' and 'skip_write' commands
   - Enables selective data capture

3. **StoreManager** (within `angiogenesis_process.py`)
   - Manages Zarr storage hierarchy
   - Writes incremental simulation data
   - Stores parameters as group attributes

4. **AngiogenesisComposer** (`vivarium_angio/composites/angiogenesis_composer.py`)
   - Standard Vivarium composer
   - Handles parameter merging and defaults
   - Generates process and topology

---

## Installation

Installed by the repository's single conda environment (CompuCell3D 4.7.0,
Python 3.12, Vivarium, Zarr, and this package in editable mode) — see
[INSTALL.md](../INSTALL.md):

```bash
conda env create -f environment.yml   # from the repository root
conda activate vc
python -c "import vivarium, cc3d, zarr, vivarium_angio; print('OK')"
```

---

## Quick Start

Run from the repository root, in the `vc` environment.

### One run, no window

```bash
python angio-gui/run_headless.py sim_time=100 --name first_run --out results
```

This is the program-facing path. It goes through the same code as a run started
from the GUI: the specification is checked against the schema, the run gets an
identity (`run_id`) and its own directory, standard output and error are
captured, and a COMBINE/OMEX archive typed with the outcome is written whether
the run succeeds, fails or times out.

```
results/first_run_<timestamp>/first_run/
├── data.zarr/            the trajectory (one store per run)
├── run_metadata.json     parameters, seed, status, specification check, code identity
├── parameter_audit.json  every value against the ranges the schema documents
├── logs/stdout.log, logs/stderr.log
└── first_run.omex        the archive (see "The archive" below)
```

### A sweep with replicates

```bash
python angio-gui/run_headless.py jem=2,4,8 sim_time=100 --replicates 3 --name jem_sweep --out results
```

A comma-separated list sweeps a numeric parameter, as in the GUI. Every run draws
its own random seed and records it; a pinned `random_seed=<n>` applies to the first
replicate only. When the batch ends, the experiment-level archive and the PDF
reports are generated (skip with `--no-report`).

### A specification saved from the GUI

```bash
python angio-gui/run_headless.py --params my_parameters.json --out results
```

`--params` takes the JSON written by the GUI's *Save Parameters*; `key=value`
arguments override it.

### What is refused

The check is `vivarium_angio/utils/spec_validation.py`, shared by the GUI, the
runner and `AngiogenesisProcess` itself:

| Specification | What happens |
|---|---|
| a key that is not a parameter (for example a misspelt name), or a value of the wrong type | refused; nothing runs |
| a value outside a declared implementation limit (`_mathematical_range`) | refused unless `--allow-inadmissible` is given; the permission is written into the run record |
| a value outside the documented working range or the recommended range | runs; its position and the basis of the range are recorded |

A refused run still leaves a directory with a `run_metadata.json` and a
failed-status archive stating why.

---

## Running Simulations

### 1. Headless runner (recommended)

See Quick Start. `experiments/run_angiogenesis_parallel.py` starts three runner
processes at once; `experiments/run_angiogenesis_sequential.py` runs a
three-point sweep in one call.

### 2. Directly through Vivarium

```python
from vivarium.core.engine import Engine
from vivarium_angio.composites.angiogenesis_composer import AngiogenesisComposer

params = {
    'angiogenesis_process': {
        'exp_name': 'my_experiment',
        'jem': 8.0,                              # EC-Medium adhesion
        'store_path': 'my_experiment/data.zarr',  # one store per run
    }
}
composite = AngiogenesisComposer(params).generate()
engine = Engine(composite=composite)
engine.update(100.0)  # 100 MCS
```

Constructing the process checks the specification and raises
`SpecificationError` for the cases in the table above (`'allow_inadmissible':
True` in the parameters permits values outside an implementation limit). Driving
the engine yourself gives you the trajectory only: the run identity, logs,
failure capture and the archive for every outcome are produced by the runner and
the GUI, not by the process. Use the runner unless you are composing this process
with others.

Give every run its own `store_path`. A store holds one run; the process refuses
to start into a store that already contains recorded steps. Run one simulation
per Python process (CompuCell3D keeps global state).

---

## Reading a trajectory

```python
import zarr

root = zarr.open('results/first_run_<timestamp>/first_run/data.zarr', mode='r')
print(dict(root.attrs)['params'])           # the parameters of the run
steps = sorted(int(k) for k in root.keys()) # recorded MCS, e.g. 10, 20, ...
data = root[str(steps[-1])]['data'][:]      # shape (200, 200, 1, 3)

cell_types = data[..., 0]   # 0 = Medium, 1 = EC
cell_ids = data[..., 1]     # cell identifiers
vegf = data[..., 2]         # VEGF concentration (model units)
```

Network measures (clusters, largest cluster, boundary sites, compactness) are
defined once, in `vivarium_angio/utils/network_metrics.py`, on the model's
lattice: four-neighbour connectivity, periodic in x and y. The GUI analysis
window and the archive's `metrics.csv` both use it.

```python
from vivarium_angio.utils import network_metrics as nm
sizes = nm.cluster_sizes(cell_types == 1)
print(len(sizes), max(sizes), nm.network_perimeter(cell_types == 1))
```

---

## The archive

Each run's `.omex` is a COMBINE archive (a zip file):

| Entry | Content |
|---|---|
| `simulation.sedml` | SED-ML description (successful runs only) |
| `status.json` | machine-readable outcome |
| `run_metadata.json`, `sim_params.json` | resolved parameters, seed, specification check, code identity |
| `metadata.rdf` | OMEX metadata (creator, licence, citation) |
| `metrics.csv` | cluster count, cell density, largest cluster, mean VEGF per recorded step |
| `zarr/<run>/` | the full trajectory |
| `logs/` | captured standard output and error |
| `model/parameter_audit.json` | every value against the schema's documented ranges |
| `model/environment.json` | Python, platform and package versions |
| `model/angiogenesis.cc3d`, `model/Simulation/` | the run as a native CompuCell3D project |
| `model/run_model.py`, `model/run_params.json` | re-run through Vivarium |
| `model/src/` | a record of the Python module that executed the run (not an importable package) |

Re-executing, from the unpacked archive:

```bash
python -m cc3d.run_script -i model/angiogenesis.cc3d -o out   # stock CompuCell3D
python model/run_model.py                                      # Vivarium path
```

The native project writes `model/native_output/step_<MCS>.npy` (beside the
project, not into `-o`); `run_model.py` writes `model/rerun_output/data.zarr`.
With the same software on one processor, each recorded step equals the archived
one (`tests/test_angio_reexecution.py` runs both and compares).

Reports are built from the archives alone:

```bash
python vivarium-angio/make_omex_combo_report.py results/jem_sweep_<timestamp>
```

---

## Architecture Comparison

### Integrated vs Decoupled Approaches

| Feature | **Integrated** (vivarium-angio) | **Decoupled** (vivarium-vcornea) |
|---------|--------------------------------|----------------------------------|
| **Runtime control** | ✅ Full control via `step()` | ❌ Fire-and-forget subprocess |
| **Incremental data** | ✅ Every 10 steps during run | ❌ Only after completion |
| **Checkpointing** | ✅ Can pause/resume | ❌ Must run to completion |
| **Data format** | Unified Zarr hierarchy | Separate CSV/Parquet files |
| **Process isolation** | ⚠️ Required (multiprocessing) | ✅ Automatic (subprocess) |
| **Implementation** | Complex (API integration) | Simple (wrap existing model) |
| **Portability** | Moderate (requires refactoring) | High (any CC3D model) |
| **Concurrent writes** | ⚠️ Needs locking on Windows | ✅ Separate files per run |
| **Best for** | New models, real-time steering | Existing models, stability |

### When to Use Integrated Architecture

**Choose Integrated if you need:**
- Real-time data access during simulation
- Runtime parameter steering
- Checkpointing/resuming capability
- Unified data management (single Zarr store)
- Cloud/distributed deployment (Zarr is cloud-native)

**Choose Decoupled if you need:**
- Maximum stability (subprocess isolation)
- Wrapping existing CC3D models with minimal changes
- Simple file-based outputs (CSV, Parquet)
- No concern about runtime interactivity

---

## Advanced Usage

### Custom Parameters

All biologically meaningful parameters are exposed via the Vivarium ports schema:

```python
params = {
    'angiogenesis_process': {
        'exp_name': 'custom_run',

        # Cell adhesion
        'jee': 2.0,     # EC-EC adhesion energy
        'jem': 4.0,     # EC-Medium adhesion energy

        # Chemotaxis
        'lchem': 500.0, # Chemotaxis strength
        'lsc': 0.1,     # Chemotaxis saturation

        # VEGF dynamics
        'vedir': 1.0,   # VEGF diffusion rate
        'veder': 0.3,   # VEGF decay rate
        'vesec': 0.3,   # VEGF secretion rate (by ECs)
    }
}
```

## Troubleshooting

### Issue 1: "No module named 'zarr'"

**Solution:**
```bash
conda activate vc
pip install zarr
```

### Issue 2: "VEGF field does not exist" or "Cells 0" on a second run

**Cause:** CompuCell3D global state is not cleaned up between runs in one process.

**Solution:** One simulation per Python process. The headless runner and the GUI
start a new process for every run.

### Issue 3: Exit code 3221225477 (Windows) at interpreter shutdown

**Cause:** a CompuCell3D C++ cleanup fault during Python teardown, after the
trajectory has been written. The runner and the GUI exit the simulation process
before that teardown and decide the run's status from its record, not from this
code.

### Issue 4: "Refusing to run into ... it already holds N recorded step(s)"

**Cause:** the store named by `store_path` (default `temp_store.zarr` in the
working directory) already contains a run.

**Solution:** give the run its own `store_path`, or use the runner, which
creates a new directory for every run.

---

## Project Structure

```
vivarium-angio/
├── vivarium_angio/
│   ├── processes/angiogenesis_process.py   # AngiogenesisProcess + its parameter schema
│   ├── composites/angiogenesis_composer.py # Vivarium composer
│   └── utils/                              # OMEX/SED-ML export, parameter audit, provenance
├── experiments/                            # example scripts built on the headless runner
├── make_omex_combo_report.py               # PDF reports, built from the OMEX archives alone
├── test_angio_*.py                         # tests (run with `pytest` from the repo root)
└── pyproject.toml
```

The full parameter schema is tabulated in Supplementary Table S1 of the paper.

---

## Citation

Please cite the accompanying article and the archived software release — see the
[repository README](../README.md#how-to-cite) and [`CITATION.cff`](../CITATION.cff).
The angiogenesis model is adapted from the contact-inhibited chemotaxis model of
Merks et al. (2008), which is the reference each archive cites; cell elongation,
the mechanism studied in Merks et al. (2006), is not represented:

> Merks RMH, Perryn ED, Shirinifard A, Glazier JA. *Contact-inhibited chemotaxis in
> de novo and sprouting blood-vessel growth.* PLoS Computational Biology.
> 2008;4(9):e1000163. doi:[10.1371/journal.pcbi.1000163](https://doi.org/10.1371/journal.pcbi.1000163)

> Merks RMH, Brodsky SV, Goligorksy MS, Newman SA, Glazier JA. *Cell elongation is
> key to in silico replication of in vitro vasculogenesis and subsequent remodeling.*
> Developmental Biology. 2006;289(1):44–54. doi:[10.1016/j.ydbio.2005.10.003](https://doi.org/10.1016/j.ydbio.2005.10.003)

CompuCell3D: Swat et al., *Methods Cell Biol.* 2012;110:325–66,
doi:[10.1016/B978-0-12-388403-9.00013-8](https://doi.org/10.1016/B978-0-12-388403-9.00013-8).
Vivarium: Agmon et al., *Bioinformatics* 2022;38(7):1972–9,
doi:[10.1093/bioinformatics/btac049](https://doi.org/10.1093/bioinformatics/btac049).

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

---

## License
MIT — see the repository [LICENSE](../LICENSE).


---

## Acknowledgments

- CompuCell3D team for the simulation framework
- Vivarium team for the multiscale modeling engine
- Contributors and testers

---

## Support

For issues, questions, or discussions:
- Open an issue on GitHub
- [GitHub Issues](https://github.com/VaninJoel/schema-driven-interfaces/issues)
- Documentations: 
  - [CompuCell3D](https://compucell3dreferencemanual.readthedocs.io/en/latest/) 
  - [Vivarium](https://vivarium-core.readthedocs.io/en/latest/)
  - [Zarr](https://zarr.readthedocs.io/en/stable/quickstart.html)

---

**Happy Simulating!** 
