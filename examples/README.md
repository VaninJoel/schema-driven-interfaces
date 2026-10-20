# Example runs

One default run of each case study, made with the released **v1.0.0** Windows
installer exactly as a user would: open the app, enter an experiment name, press
**Run Simulation**. Every parameter was left at its schema default.

| Case study | Audit report (human-readable) | Run archive (COMBINE/OMEX) |
|---|---|---|
| **Angio-GUI** (integrated pattern) | [Angio-GUI_example_run_report.pdf](Angio-GUI_example_run_report.pdf) | [Angio-GUI_example_run.omex](Angio-GUI_example_run.omex) |
| **V-Cornea GUI** (decoupled pattern) | [V-Cornea_example_run_report.pdf](V-Cornea_example_run_report.pdf) | [V-Cornea_example_run.omex](V-Cornea_example_run.omex) |

The **report** is the PDF the GUI writes automatically when a run finishes. It is
generated from the archive alone and shows what the archive records: the
archive's own integrity checks, provenance, run identity (seed, schema
fingerprint, code version), each parameter's value against its documented
ranges, how to read the SED-ML, the recorded outputs, and plots of the packaged
data.

The **archive** is the complete record of the run. It is a zip file, so any unzip
tool can open it. It contains:

- `simulation.sedml`: the SED-ML simulation description.
- `run_metadata.json`: the resolved parameters and provenance.
- `parameter_audit.json`: every parameter checked against its schema.
- `environment.json` and `status.json`: the software environment and run outcome.
- The logs, the model files, and the raw outputs.

| | Angio-GUI | V-Cornea |
|---|---|---|
| Run ID | `c6a384f7b258459da134330ac402732d` | `e03dbb758e394a6c99f771f9ef9dbf74` |
| Random seed (drawn) | 799091067 | 327637287 |
| Schema fingerprint | `sha256:0a6c2ceaca8b9cdf` | `sha256:d3c5ca23a40e24f9` |
| Code | `v1.0.0` (commit `043fb10`) | `v1.0.0` (commit `043fb10`) |
| Status | success | success |

The schema fingerprints match the parameter tables in the article's
supplementary material.
