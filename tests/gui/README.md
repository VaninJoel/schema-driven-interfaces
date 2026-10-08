# Headless GUI tests

Drive both real PyQt5 GUIs (V-Cornea, Angio) under Qt's `offscreen` platform:
no display, no CompuCell3D, no simulation subprocess. The schema, widgets,
dialogs, validation and documentation export are the real code.

```
conda run -n vc --no-capture-output pytest tests/gui -v
# longer / different random sessions
GUI_FUZZ_STEPS=1000 GUI_FUZZ_SEED=11,12 conda run -n vc --no-capture-output pytest tests/gui -k random
```

| File | What it checks |
|---|---|
| `test_descriptors_appear.py` | every parameter has a control and an ⓘ button; expertise level changes editability, not visibility; the ⓘ dialog shows each documented field (ranges with their evidence statement, default provenance with locator, literature, ontology term, expected behaviour, dependencies, presets, evidence basis); the validation dialog states the range evidence and never borrows the default's citation; the Markdown export lists every parameter with its evidence; every ⓘ button opens its dialog |
| `test_every_button.py` | every button in every tab (and in the post-run state) is clicked with no exception escaping; a coverage JSON lists what was reached; Run → confirm → worker → finished handler round-trips with a fake worker; Save/Load round-trip |
| `test_random_interaction.py` | seeded random operator sessions (type valid/invalid/sweep values, click, toggle, switch tabs/levels/presets, start runs) must never raise or close the window; invalid values are flagged, not fatal |

How it stays headless and fast: `QDialog.exec_` shows, paints and closes;
`QMessageBox`/`QFileDialog` statics answer immediately; `SimulationWorker` is a
fake that writes a `run_metadata.json` and emits `finished`; the angio window
gets a schema-only `AngiogenesisProcess` subclass whose constructor does not
start CC3D (the schema and presets are class attributes). `sys.excepthook` is
captured so an exception inside a Qt slot fails the test with a traceback
instead of aborting the interpreter.

## What the first run of this suite found (2026-10-06)

All fixed on this branch; each has a test that would catch a regression.

| Finding | Where | Test |
|---|---|---|
| Angio ⓘ dialog rendered neither `_literature` nor `_ontology_term`, hid the short description when a long one existed, and read `equation`/`page` from the old `_reference_paper` shape | `angio-gui/gui/main_window.py` | `test_info_dialog_shows_each_documented_field` |
| V-Cornea ⓘ dialog showed only the converted display unit, never the documented `_unit` string | `vcornea-gui/gui/main_window.py` | same, `_unit` case |
| Both validation dialogs attributed the physiological range to the default value's citation | both `main_window.py` | `test_validation_dialog_states_range_evidence` |
| `validate_parameter_value` did the same in its warning text, treated `10.0` as a type error for an `int` default, and never checked `_validation_pattern` / `_max_length` | both `utils/schema_utils.py` | `test_every_preset_applies_without_a_type_error`, `test_experiment_name_never_produces_an_unsafe_folder` |
| Applying the angio default preset stored the string `'10.0'` for `write_frequency` (readiness audit 4.4, now reproduced) | both `main_window.py` (`_int_from_text`) | `test_every_preset_applies_without_a_type_error` |
| V-Cornea accepted any text as the run name; the fuzzer created folders named `1,2,3` and `-1` | `vcornea-gui/gui/main_window.py` | `test_experiment_name_never_produces_an_unsafe_folder` |
| **Not fixed, documented as a strict expected failure:** with a few sweep lists typed in and the replicate count raised, Run started every worker at once (72 threads observed; readiness audit 3.3, no concurrency cap). The fuzzer now keeps spin values small so sessions stay bounded | both `launch_batch_simulation` | `test_batch_fan_out_is_capped` (xfail; flip when a queue lands) |
| The angio widget registry had no `container` entry, so nothing could find a row's ⓘ button programmatically | `angio-gui/gui/main_window.py` | `test_every_parameter_has_a_control_and_an_info_button` |

Not covered yet: the analysis windows beyond opening them (they need real run
data), the real `SimulationWorker` (needs CC3D), and pixel-level layout. The
angio window still constructs the schema through a `AngiogenesisProcess`
subclass that skips `__init__`; the proper fix is a class-level schema accessor
in `vivarium_angio` (readiness audit 4.2).
