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

This installs Python 3.12, CompuCell3D 4.7.0, PyQt5, the data/analysis stack,
and editable installs of the local `vivarium-vcornea` and `vivarium-angio`
packages.

> If the solve is slow on an older conda, either enable the libmamba solver
> (`conda install -n base conda-libmamba-solver`) or use
> `mamba env create -f environment.yml`.

`vc` is just the default name — nothing depends on it. When you launch a GUI
from this environment, both models run CompuCell3D **in the same interpreter**
that is already active, so there is no separate env to configure and the env
name does not matter. (If you choose a different name, `conda activate <name>`
in place of `conda activate vc` below.)

> Advanced: you can keep the GUI in one env and CompuCell3D in another. If the
> GUI's interpreter can't import `cc3d`, the V-Cornea model falls back to
> launching it via `conda run -n vc` (override the env with the process
> parameter `cc3d_conda_env_name`). The single-env install above avoids this
> entirely.

## 3. Launch a GUI

```bash
# V-Cornea (corneal epithelium)
cd vcornea-gui && python run_gui.py

# Angiogenesis
cd ../angio-gui && python run_gui.py
```

Each GUI finds its sibling Vivarium process package by relative path, so keep the
folders arranged as they are in this repository.

Shortcut for a development checkout: `./run_local.sh` (Linux/macOS/WSLg) finds
the `vc` env automatically, launches one or both GUIs, and mirrors their console
output to `.logs/run_local/`. `./run_local.sh check` verifies the interpreter,
`./run_local.sh tests` runs the headless GUI test suite.

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

- **`CondaToSNonInteractiveError` / "Terms of Service have not been accepted"** —
  on a fresh Miniconda/Anaconda, `conda env create` can refuse to proceed until
  you accept the ToS for Anaconda's default channels, even though this project
  only uses `conda-forge` and `compucell3d`. Accept them once and re-run:
  ```bash
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
  ```
- **`compucell3d` not found during solve** — make sure the `compucell3d` channel
  is reachable; the `environment.yml` already lists it. Corporate proxies
  sometimes block it.
- **GUI won't open / `qt.qpa.plugin` errors** — you have no display. Run on a
  desktop session, or use X11 forwarding; the headless simulation/analysis paths
  still work without one.
- **Simulation exits immediately with no `cell_count_*.csv`** — CompuCell3D isn't
  importable in the environment you launched the GUI from. Activate the env and
  confirm `python -c "import cc3d; print('OK')"` works; if it doesn't, re-create
  the environment (`conda env create -f environment.yml`). Per-replicate
  `stdout.log`/`stderr.log` files in the experiment's `logs/` dir hold CC3D's
  real error.
