# Installation

Everything runs in a single self-contained **conda environment** named `vc`.
CompuCell3D (the simulation engine) is distributed only through conda, so conda
is the supported way to install — one file sets up the whole stack.

## 1. Prerequisites

- [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
  (conda ≥ 23.10 recommended — it uses the fast `libmamba` solver by default).
- A C-capable OS that CompuCell3D 4.7.0 supports: Linux, Windows, or macOS.
- For running the **GUIs** (PyQt5 desktop apps) you need a graphical display.
  On Linux/WSLg this works out of the box; over SSH use X11 forwarding
  (`ssh -X`). The simulation engine and analysis loaders do not need a display.

## 2. Create the environment

From the repository root:

```bash
conda env create -f environment.yml
conda activate vc
```

This installs Python 3.12, CompuCell3D 4.7.0, the data/analysis stack, and
editable installs of the local `vivarium-vcornea` and `vivarium-angio` packages.

> If the solve is slow on an older conda, either enable the libmamba solver
> (`conda install -n base conda-libmamba-solver`) or use
> `mamba env create -f environment.yml`.

The environment is named **`vc`** on purpose: the GUI launches CompuCell3D via
`conda run -n vc ...` by default (`cc3d_conda_env_name='vc'`), so no further
configuration is needed. If you rename the env, set `cc3d_conda_env_name`
accordingly in the GUI before running a simulation.

## 3. Launch a GUI

```bash
# V-Cornea (corneal epithelium)
cd vcornea-gui && python run_gui.py

# Angiogenesis
cd ../angio-gui && python run_gui.py
```

Each GUI finds its sibling Vivarium process package by relative path, so keep the
folders arranged as they are in this repository.

## 4. Verify (optional)

```bash
conda activate vc
python -c "import cc3d; print('CompuCell3D OK')"
python -c "import vivarium_vcornea, vivarium_angio; print('wrappers OK')"
```

## Updating

After pulling new changes, refresh the environment if `environment.yml` changed:

```bash
conda env update -f environment.yml --prune
```

## Troubleshooting

- **`compucell3d` not found during solve** — make sure the `compucell3d` channel
  is reachable; the `environment.yml` already lists it. Corporate proxies
  sometimes block it.
- **GUI won't open / `qt.qpa.plugin` errors** — you have no display. Run on a
  desktop session, or use X11 forwarding; the headless simulation/analysis paths
  still work without one.
- **Simulation exits immediately with no `cell_count_*.csv`** — the GUI couldn't
  find CompuCell3D in the `vc` env. Confirm `conda run -n vc python -c "import cc3d"`
  works, and that `cc3d_conda_env_name` matches your env name.
