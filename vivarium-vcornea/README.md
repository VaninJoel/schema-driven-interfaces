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

The full parameter schema — meaning, units, default, implementation limit and
working range, and what each range rests on — is tabulated in
Supplementary Table S2 of the paper.

## What a run writes

Per replicate: the model's native outputs (`cell_count_*.csv`,
thickness `*.parquet`, …), `logs/stdout.log` and `logs/stderr.log`,
`run_metadata.json`, `parameter_audit.json`, and a `<run>.omex` archive that embeds
the runnable project, the SED-ML description, the environment record and a status
record. Failed, cancelled and timed-out runs keep the same structure and are
marked as unsuccessful.

## Re-executing, from the unpacked archive

A run archive (`<run>.omex`, a zip file) carries the model project this
replicate executed under `model/`: the unmodified model code, the `Parameters.py`
generated for the replicate and the CC3DML with its seed. Stock CompuCell3D runs
it; neither the wrapper nor the GUI is needed.

```bash
unzip <run>.omex -d replay && cd replay
python -m cc3d.run_script -i model/vCornea_v2.cc3d -o out
python <repository>/vivarium-vcornea/compare_replay.py . model/Simulation <final step>
```

The model writes its tables beside its code, in `model/Simulation/`
(`cell_count_<N>.csv`, `surfactant_<N>.csv`, `thickness_rep_<N>.parquet`, where
`N` is `SimTime + 1`, the final step); `-o out` receives only CompuCell3D's copy
of the project. `compare_replay.py` compares the three tables with the archived
ones, row for row.

A full-length run takes hours (the 30-day examples took about 5 h each). For a
quick check, lower `SimTime` in `model/Simulation/Parameters.py` (240 steps is
one simulated day, a few minutes) before running: the tables of the shorter
replay must equal the archived tables over the period they cover, and
`compare_replay.py` checks exactly that. With the same software on one
processor the replay is identical; what was observed in a fresh environment is
tabulated in [`examples/README.md`](../examples/README.md#re-executing-the-examples).
The seed reaches both random generators the model uses, CompuCell3D's through
the CC3DML and Python's through the last lines of `Parameters.py`.

## Tests

```bash
pytest vivarium-vcornea      # from the repository root
```

`E2E_test.py` (not collected by default) runs a real, short CompuCell3D simulation.

## Citation and license

See the [repository README](../README.md#how-to-cite). MIT license
([LICENSE](../LICENSE)).
