# vivarium-vcornea

`VCorneaProcess`: a Vivarium process that orchestrates the published
[V-Cornea](../vcornea_paper/) CompuCell3D model — the **decoupled** pattern of the
paper (Section 4). Its `ports_schema()` is the single source of truth for the
model's 79 exposed parameters and drives the [V-Cornea GUI](../vcornea-gui/).

For each replicate the process copies the CC3D project into a private workspace,
writes the resolved parameters into that copy's `Simulation/Parameters.py`,
redirects outputs to the replicate's own folder, and launches CompuCell3D as a
separate operating-system process. The source project is never modified. The
run is then classified (a zero exit code without the expected output counts as a
failure), and packaged with its provenance as a COMBINE/OMEX archive.

## Installation

Installed by the repository's single conda environment — see
[INSTALL.md](../INSTALL.md):

```bash
conda env create -f environment.yml   # from the repository root
conda activate vc
```

(`environment.yml` installs this package in editable mode, with the `[validation]`
extra used by the OMEX/SED-ML conformance test.)

## Using the process from Python

```python
from vivarium.core.engine import Engine
from vivarium_vcornea.composites import VCorneaComposer

composer = VCorneaComposer({'vcornea': {'replicates': 1}})
initial_state = {'inputs': {'SimTime': 100, 'IsInjury': True, 'InjuryTime': 50},
                 'outputs': {}}
sim = Engine(composite=composer.generate(), initial_state=initial_state)
sim.update(1.0)
```

The CC3D project is found automatically when this package sits next to
`vcornea_paper/` in the repository; otherwise pass `vcornea_project_path`.
CompuCell3D is launched with the current interpreter when it can import `cc3d`
(the single-environment install), and through `conda run -n <cc3d_conda_env_name>`
(default `vc`) otherwise. More examples are in [`experiments/`](experiments/).

The full parameter schema — meaning, units, default, admissible and
evidence-supported ranges and their sources — is tabulated in
Supplementary Table S2 of the paper.

## What a run writes

Per replicate: the model's native outputs (`cell_count_*.csv`,
thickness `*.parquet`, …), `logs/stdout.log` and `logs/stderr.log`,
`run_metadata.json`, `parameter_audit.json`, and a `<run>.omex` archive that embeds
the runnable project, the SED-ML description, the environment record and a status
record. Failed, cancelled and timed-out runs keep the same structure and are
marked as unsuccessful.

## Tests

```bash
pytest vivarium-vcornea      # from the repository root
```

`E2E_test.py` (not collected by default) runs a real, short CompuCell3D simulation.

## Citation and license

See the [repository README](../README.md#how-to-cite). MIT license
([LICENSE](../LICENSE)).
