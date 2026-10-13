"""Figure 2 (docs/figures/figure2) is rendered from the live code; its caption
records the schema fingerprints it was rendered from. A schema change without
re-rendering the figure fails here.

    Re-render:  python docs/figures/figure2/make_figure2.py
"""
from pathlib import Path

CAPTION = Path(__file__).resolve().parents[1] / 'docs' / 'figures' / 'figure2' / 'caption.md'


def test_figure2_was_rendered_from_the_current_schemas():
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    from vivarium_angio.utils.provenance import schema_fingerprint as angio_fp
    from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
    from vivarium_vcornea.utils.provenance import schema_fingerprint as vcornea_fp
    caption = CAPTION.read_text(encoding='utf-8')
    for name, fp in (('Angio-GUI', angio_fp(AngiogenesisProcess().ports_schema())),
                     ('V-Cornea', vcornea_fp(VCorneaProcess().ports_schema()))):
        assert f"`{fp}` ({name})" in caption, (
            f"Figure 2 is stale for {name} (schema is now {fp}); re-render with "
            "`python docs/figures/figure2/make_figure2.py`")
