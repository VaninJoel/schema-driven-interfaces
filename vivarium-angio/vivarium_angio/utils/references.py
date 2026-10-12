"""Angiogenesis model bibliography.

Single citation registry for the schema's `_reference_paper` (default-value
provenance), `_literature` and `_range_evidence[...]['refs']` keys, mirroring
`vivarium_vcornea.utils.references`. Keys are short string handles.
"""

REFERENCES = {
    'merks2006': {
        'source': 'Merks et al., 2006',
        'cite': 'Merks RMH, Brodsky SV, Goligorsky MS, Newman SA, Glazier JA. Cell elongation is key to in silico replication of in vitro vasculogenesis and subsequent remodeling. Dev Biol. 2006;289(1):44–54.',
        'title': 'Cell elongation is key to in silico replication of in vitro vasculogenesis and subsequent remodeling',
        'doi': '10.1016/j.ydbio.2005.10.003',
        'pmid': '16325173',
        'url': 'https://doi.org/10.1016/j.ydbio.2005.10.003',
        'journal': 'Developmental Biology',
        'year': 2006,
    },
    'merks2008': {
        # The contact-inhibited chemotaxis model this core re-implements
        # (chemotaxis only at cell–medium interfaces, saturating response).
        'source': 'Merks et al., 2008',
        'cite': 'Merks RMH, Perryn ED, Shirinifard A, Glazier JA. Contact-inhibited chemotaxis in de novo and sprouting blood-vessel growth. PLoS Comput Biol. 2008;4(9):e1000163.',
        'title': 'Contact-inhibited chemotaxis in de novo and sprouting blood-vessel growth',
        'doi': '10.1371/journal.pcbi.1000163',
        'pmid': '18802455',
        'url': 'https://doi.org/10.1371/journal.pcbi.1000163',
        'journal': 'PLoS Computational Biology',
        'year': 2008,
    },
    'model_specific': {
        # Defaults chosen for this CompuCell3D re-implementation; no published
        # source gives these numbers. See each parameter's _reference_paper.notes
        # for how they relate to the Merks et al. values.
        'source': 'This model (angiogenesis_process.py)',
        'cite': 'vivarium_angio.processes.angiogenesis_process — CompuCell3D re-implementation of the Merks et al. (2008) contact-inhibited chemotaxis model; parameter defaults set for this implementation.',
        'title': 'Parameter defaults set for this specific model implementation',
        'doi': None,
        'url': 'https://github.com/VaninJoel/schema-driven-interfaces',
    },
}

