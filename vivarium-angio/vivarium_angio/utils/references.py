"""Angiogenesis model bibliography.

Single citation registry for the schema's `_reference_paper` (default-value
provenance), `_literature` and `_range_evidence[...]['refs']` keys, mirroring
`vivarium_vcornea.utils.references`. Keys are short string handles.
"""

REFERENCES = {
    'merks2006': {
        'source': 'Merks et al., 2006',
        'title': 'Cell elongation is key to in silico replication of in vitro vasculogenesis and subsequent remodeling',
        'doi': '10.1016/j.ydbio.2005.10.003',
        'url': 'https://doi.org/10.1016/j.ydbio.2005.10.003',
        'journal': 'Developmental Biology',
        'year': 2006,
    },
    'merks2008': {
        'source': 'Merks & Glazier, 2008',
        'title': 'A cell-centered approach to developmental biology',
        'doi': '10.1016/j.physa.2007.11.053',
        'url': 'https://doi.org/10.1016/j.physa.2007.11.053',
        'journal': 'Physica A',
        'year': 2008,
    },
    'model_specific': {
        'source': 'This Model',
        'title': 'Parameters determined for this specific model implementation',
        'doi': None,
        'url': None,
}
    }
