# Schema-Driven Interfaces

**Schema-driven graphical interfaces and provenance capture for agent-based
biological models, wrapping CompuCell3D (CC3D) simulations as
[Vivarium](https://vivarium-collective.github.io/) processes.**

This repository is the software accompanying the article

> Vanin J, Getz M, Sego TJ, Mahony C, Glazier JA, Veschini L. *Addressing the
> Usability Gap in In Silico Experiments: Schema-Driven Interfaces and Provenance
> for Reproducible Simulations.* (submitted)

The unifying idea: a simulation is exposed as a Vivarium process whose
`ports_schema()` declares every parameter together with its meaning, units,
default, admissible and evidence-supported ranges, and the evidence behind them.
A PyQt5 GUI is **generated from that schema**, and the same definitions validate
each run and are written into its provenance record — so the interface, the
validation, the documentation and the run archive cannot drift apart.

Two case studies demonstrate the two architectural patterns discussed in the paper:

| Case study | Pattern | How the GUI drives CompuCell3D |
|---|---|---|
| **Angio-GUI** (vascular network formation) | **Integrated** (Section 3) | A worker process advances the model step by step through CC3D's SimService API and records state to a Zarr trajectory. |
| **V-Cornea GUI** (corneal epithelium homeostasis and injury) | **Decoupled** (Section 4) | Each replicate runs an unmodified copy of the published CC3D project as an isolated subprocess; native outputs are collected afterwards. |

Every run, in both apps, receives a durable run identity and is packaged as a
COMBINE/OMEX archive (SED-ML) containing its resolved parameters, parameter audit,
environment record, logs, outputs and status — including failed and cancelled runs.

### 📄 See what a run produces

These are two real runs, one per case study, made with the v1.0.0 installer and
default parameters. Each has a human-readable audit report and the full run archive.

| Case study | Audit report | Run archive |
|---|---|---|
| **Angio-GUI** | [📄 Angio-GUI example report (PDF)](examples/Angio-GUI_example_run_report.pdf) | [Angio-GUI_example_run.omex](examples/Angio-GUI_example_run.omex) |
| **V-Cornea GUI** | [📄 V-Cornea example report (PDF)](examples/V-Cornea_example_run_report.pdf) | [V-Cornea_example_run.omex](examples/V-Cornea_example_run.omex) |

The [examples/](examples/) folder explains what each report and archive contains.

---

## ⬇️ Download & install — no coding required

Pre-built desktop installers bundle **everything** (including CompuCell3D) — no
Python or conda setup. Download the one for your computer, then follow the last
column. All builds live on the **[Releases page](https://github.com/VaninJoel/schema-driven-interfaces/releases/latest)**.

| Your computer | Download | Then |
|---|---|---|
| **Windows** (64-bit) | [Windows installer (.zip)](https://github.com/VaninJoel/schema-driven-interfaces/releases/latest/download/SchemaDrivenInterfaces-Windows-x86_64.zip) | Extract the zip, double-click **`install.bat`**, then open **V-Cornea Simulation** / **Angiogenesis Simulation** from the Start menu. |
| **macOS** (Apple Silicon) | [macOS installer (.sh)](https://github.com/VaninJoel/schema-driven-interfaces/releases/latest/download/SchemaDrivenInterfaces-macOS-arm64.sh) | Open Terminal and run `bash ~/Downloads/SchemaDrivenInterfaces-macOS-arm64.sh`, then launch from the desktop. |
| **Linux** (64-bit) | [Linux installer (.sh)](https://github.com/VaninJoel/schema-driven-interfaces/releases/latest/download/SchemaDrivenInterfaces-Linux-x86_64.sh) | In a terminal, run `bash ~/Downloads/SchemaDrivenInterfaces-Linux-x86_64.sh`, then launch from the app menu. |

Installs into your user folder — **no admin rights needed**. The installers are
unsigned, so Windows SmartScreen ("More info → Run anyway") and macOS Gatekeeper
may ask for confirmation the first time. Prefer to run from the source code
instead? See [Run from source](#run-from-source-developers).

**Where your runs are saved:** by default in your Documents folder, under
`Documents/SchemaDrivenInterfaces/vcornea-gui/experiments` and
`Documents/SchemaDrivenInterfaces/angio-gui/experiments`. Use **Browse...** in
the app to choose another folder. Reinstalling or updating never deletes saved runs.

---

## Run from source (developers)

Everything runs in a single self-contained conda environment (`vc`) — one file
sets up CompuCell3D 4.7.0, Python 3.12 and the full Python stack:

```bash
git clone https://github.com/VaninJoel/schema-driven-interfaces.git
cd schema-driven-interfaces
conda env create -f environment.yml
conda activate vc
cd vcornea-gui && python run_gui.py     # or: cd angio-gui && python run_gui.py
```

See **[INSTALL.md](INSTALL.md)** for prerequisites, the Windows-specific step,
display (X11) notes, verification and troubleshooting.

### Run the tests

From the repository root, with the environment active:

```bash
pytest
```

This runs, in one session, the unit tests of both Vivarium packages (including the
check that every exposed parameter carries the required schema fields), the
COMBINE/OMEX and SED-ML conformance checks, and the headless GUI tests
([`tests/gui/`](tests/gui/)).

---

## Repository layout

| Folder | What it is |
|---|---|
| [`vivarium-angio/`](vivarium-angio/) | `AngiogenesisProcess`: the Vivarium process (and its parameter schema) for the angiogenesis CC3D model — integrated pattern. |
| [`angio-gui/`](angio-gui/) | **Angio-GUI**: the schema-driven PyQt5 application for the angiogenesis model. |
| [`vivarium-vcornea/`](vivarium-vcornea/) | `VCorneaProcess`: the Vivarium process (and its parameter schema) that orchestrates the V-Cornea model — decoupled pattern. |
| [`vcornea-gui/`](vcornea-gui/) | **V-Cornea GUI**: the schema-driven PyQt5 application for the V-Cornea model. |
| [`vcornea_paper/`](vcornea_paper/) | The published **V-Cornea** CompuCell3D model (Vanin et al. 2025, *PLOS Comput Biol* 21(12):e1013410), unmodified, in its `Local/` and `HPC/` layouts. |
| [`examples/`](examples/) | One example run per case study: audit report (PDF) and run archive (OMEX). |
| [`tests/`](tests/) | Repository-level tests (headless GUIs). |
| [`installer/`](installer/) | Scripts that build the self-contained desktop installers. |

Each GUI finds its sibling process package by relative path (e.g.
`vcornea-gui/run_gui.py` expects `../vivarium-vcornea`), so keep the folders
arranged as they are in this repository.

---

## Status & scope

This is research software. The two models are used as architectural demonstrators
and as mechanistic, hypothesis-generating tools, not as quantitative clinical
predictors. The angiogenesis model is adapted from Merks et al. (2006, 2008) and is
not a re-validation of the original results. The V-Cornea project in
`vcornea_paper/` is identical to the published model
([github.com/VaninJoel/vCornea](https://github.com/VaninJoel/vCornea)); the GUI
writes parameters only into a private per-replicate copy of it.

## How to cite

Please cite the article above and the archived release of this software; see
[`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button uses it).
If you use the V-Cornea model itself, also cite Vanin et al. (2025),
*PLOS Comput Biol* 21(12):e1013410,
[doi:10.1371/journal.pcbi.1013410](https://doi.org/10.1371/journal.pcbi.1013410).

## License

[MIT](LICENSE). CompuCell3D, Vivarium, PyQt5 and the other dependencies are
distributed under their own licenses.
