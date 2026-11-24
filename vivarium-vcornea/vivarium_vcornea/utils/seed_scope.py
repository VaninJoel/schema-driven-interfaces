"""What the recorded random seed does and does not determine.

The single source of this statement. The run record (run_metadata.json), the
archive (status.json, SED-ML notes) and the reports all take their wording from
here, so they cannot say different things about the seed.

Three different claims, kept apart: a seed was requested; it was applied
(`random_seed_applied` in the run record); it is sufficient to replay the run.

The model draws random numbers from two generators: CompuCell3D's own (the
Cellular Potts dynamics) and Python's `random` module (superficial-cell
sloughing, `random.random()` in the death steppable). CompuCell3D seeds only its
own. The wrapper therefore seeds both from the one recorded seed: CompuCell3D's
through <Potts>/<RandomSeed> in the per-replicate CC3DML, Python's through the
generated Parameters.py, which the model imports at start-up (see
PYTHON_SEED_LINES). The model's steppable code is not edited, and both files are
archived, so re-executing the archived project applies the same two seeds.
"""

# Appended to the generated Parameters.py. The steppable does
# `from Parameters import *`; names with a leading underscore are not exported by
# a star import, so this adds nothing to the model's namespace.
PYTHON_SEED_LINES = (
    "\n"
    "# Seed Python's random module from the recorded seed. The model draws\n"
    "# superficial-cell sloughing from it, and CompuCell3D seeds only its own\n"
    "# generator (set in the CC3DML). Written by the wrapper; not a model parameter.\n"
    "import random as _python_random\n"
    "_python_random.seed(random_seed)\n"
)

RANDOM_SEED_SCOPE = {
    'controls': [
        "CompuCell3D's random number generator (<Potts>/<RandomSeed> in the "
        "per-replicate CC3DML): the Cellular Potts copy attempts and every other "
        "draw CompuCell3D makes itself",
        "Python's `random` module, from which the model draws superficial-cell "
        "sloughing (`random.random()` in the death steppable): seeded with the "
        "same value by the generated Parameters.py, which the model imports at "
        "start-up",
    ],
    'does_not_control': [
        "random draws a project might make from other generators: this statement "
        "describes the paper_version project, whose steppables draw from "
        "CompuCell3D and from Python's `random` only (the STEM_ONLY variants also "
        "call numpy's generator, which is not seeded)",
        "the order in which draws are consumed if the simulator is run "
        "multi-threaded (the model is configured for one processor)",
        "differences between machines, operating systems or versions of "
        "CompuCell3D, Python and their numerical libraries",
    ],
    'consequence': (
        "On the same machine and software, with one processor, re-running with "
        "this seed and these parameters is expected to reproduce the run's output "
        "tables exactly; this is checked for short runs by the package's tests, "
        "not for a full-length simulation. Changing any parameter changes which "
        "random numbers are consumed and when, so runs that share a seed but "
        "differ in a parameter are not matched realizations. Across machines or "
        "software versions, agreement is to be judged statistically, across "
        "replicates."),
}

# One sentence for places with room for one (SED-ML notes, status.json, a report
# footnote). Derived wording; RANDOM_SEED_SCOPE above is the full statement.
SEED_SCOPE_SENTENCE = (
    "The recorded seed sets both random generators the model uses: CompuCell3D's "
    "(in the CC3DML) and Python's (in the generated Parameters.py). On the same "
    "machine and software, with one processor, the same seed and parameters are "
    "expected to reproduce the output tables exactly (checked for short runs "
    "only); with any parameter changed, or on other machines or software "
    "versions, runs are to be compared statistically, across replicates.")
