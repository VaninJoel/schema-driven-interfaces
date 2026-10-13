**Figure 2. One parameter definition, several consumers.**
(A) Abridged process-schema entry for VEGF diffusion in Angio-GUI
(`AngiogenesisProcess.ports_schema()`); each range tier carries its own evidentiary
basis. (B) The control generated from it, at three values: inside every declared
range; outside the evidence-supported range (an extrapolation warning); and outside
the implementation-admissible range (an error; launching a run with it requires the
operator's explicit confirmation). (C) The in-context
information panel rendered from the same entry. (D) The corresponding entry in the
run's parameter-audit record for a run with `vedir = 3`, classifying the
value against each tier. (E) The same format in V-Cornea (`EGF_SUPERDiffCoef`): the
declared dimension drives conversion between the stored simulator value and the
operator-facing value, and the panel shows the literal `Parameters.py` assignment and
the governing equation. All panels were generated from schema fingerprints
`sha256:0a6c2ceaca8b9cdf` (Angio-GUI) and `sha256:d3c5ca23a40e24f9` (V-Cornea).
