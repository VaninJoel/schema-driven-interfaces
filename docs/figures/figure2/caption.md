**Figure 2. One parameter definition, several consumers.**
(A) Process-schema entry for VEGF diffusion in Angio-GUI
(`AngiogenesisProcess.ports_schema()`), abridged: long strings are cut at […] and
further fields are omitted as stated in the panel. Each range carries its own basis.
The key names `_physiological_range` and `_mathematical_range` are historical: the
interface shows them as the working range (the values the model is meant to be used
with) and the implementation limit (what the model code can run with). (B) The control
generated from the entry, at three values: within the working range and the
implementation limit; outside the working range (the run proceeds and the finding is
recorded with the basis of the range, here published literature); and outside the
implementation limit (the run starts only after the operator's explicit confirmation,
which is recorded). (C) The ranges section of the in-context information panel rendered
from the same entry, with each range's evidence statement cut at […]; the working range
is labelled physiological because its basis is published literature. (D) The entry for
this parameter in the parameter-audit record of a run with `vedir = 3`
(abridged), giving the position of the value against each range. The machine label
`extrapolation` is the stored form of "outside the documented working range", which is
how reports word it. (E) The same format in V-Cornea (`EGF_SUPERDiffCoef`), from its
information panel: the declared dimension drives conversion between the stored
simulator value and the operator-facing value, and the panel shows the literal
`Parameters.py` assignment and the governing equation. Panels B, C and E are renderings
of the running interfaces and A and D are printed from the running code, at schema
fingerprints `sha256:7962f735412f08c2` (Angio-GUI) and `sha256:d3c5ca23a40e24f9` (V-Cornea). Text is at least
7 pt when the figure is printed 17 cm wide.
