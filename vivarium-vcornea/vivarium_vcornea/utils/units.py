"""Unit conversion service for V-Cornea (simulation units <-> human/display units).

Single source of truth for the spatial / temporal / derived scale mappings.

Storage is **sim-canonical**: schema ``_default`` and ``_physiological_range`` are in
simulation units (what ``Parameters.py`` / CC3D actually consume). This module converts
to physical units PURELY for display, and back to sim units only at the model-write
boundary. A conversion bug can therefore mislead a display but can never silently
corrupt a real run.

    display = sim * factor          sim = display / factor

A parameter declares a ``_dimension`` (and, for time, an optional ``_display_unit``).
Arbitrary-unit dimensions (energy, pressure, concentration, dimensionless) use an
identity factor of 1.0, so the displayed number equals the sim number.

To reuse this for another model, redefine the four scale constants below; the dimension
table is derived from them.
"""

# --- V-Cornea scale constants (the ONLY place these magic numbers live) ---
MICRONS_PER_VOXEL = 2.0    # 1 voxel edge = 2 µm
MINUTES_PER_MCS = 6.0      # 1 MCS = 6 minutes
MCS_PER_HOUR = 10.0        # 1 hour = 10 MCS
MCS_PER_DAY = 240.0        # 1 day = 240 MCS

# --- derived factors (display = sim * factor) ---
_MICRONS2_PER_VOXEL2 = MICRONS_PER_VOXEL ** 2                 # 4.0   µm² per voxel²
_DIFFUSION_FACTOR = _MICRONS2_PER_VOXEL2 / MINUTES_PER_MCS    # 0.6667 (µm²/min) per (voxel²/MCS)
_RATE_FACTOR = MCS_PER_HOUR                                   # 10.0  (1/hour) per (1/MCS)

# dimension -> (sim_unit_label, display_unit_label, factor)
_DIMENSIONS = {
    'length':        ('voxel',      'µm',      MICRONS_PER_VOXEL),
    'area':          ('voxel^2',    'µm²',     _MICRONS2_PER_VOXEL2),
    'rate':          ('1/MCS',      '1/hour',  _RATE_FACTOR),
    'diffusion':     ('voxel^2/MCS', 'µm²/min', _DIFFUSION_FACTOR),
    'concentration': ('a.u.',       'a.u.',    1.0),
    'energy':        ('a.u.',       'a.u.',    1.0),
    'pressure':      ('a.u.',       'a.u.',    1.0),
    'dimensionless': ('',           '',        1.0),
    'boolean':       ('',           '',        1.0),
    'categorical':   ('',           '',        1.0),
}

# `time` supports multiple display units; display(in unit) = MCS * factor
_TIME_FACTORS = {
    'days':    1.0 / MCS_PER_DAY,
    'hours':   1.0 / MCS_PER_HOUR,
    'minutes': MINUTES_PER_MCS,
}
DEFAULT_TIME_UNIT = 'days'

# Field global diffusion constants (sim units, voxel^2/MCS) — from vCornea_v2.xml.
# Used to bound per-cell-type DiffCoef ranges: a cell-type coefficient lies in
# [0, field global]. The field cannot transport faster than its global rate.
FIELD_GLOBAL_DIFFUSION = {
    'EGF': 186.0,
    'SLS': 5.0,
}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def factor(dimension, display_unit=None):
    """Conversion factor such that ``display = sim * factor``."""
    if dimension == 'time':
        return _TIME_FACTORS[display_unit or DEFAULT_TIME_UNIT]
    spec = _DIMENSIONS.get(dimension)
    return spec[2] if spec else 1.0


def display_unit_label(dimension, display_unit=None):
    """Human-facing unit label for a dimension (e.g. 'µm', '1/hour', 'days')."""
    if dimension == 'time':
        return display_unit or DEFAULT_TIME_UNIT
    spec = _DIMENSIONS.get(dimension)
    return spec[1] if spec else ''


def sim_unit_label(dimension):
    """Internal simulation unit label (e.g. 'voxel', '1/MCS', 'MCS')."""
    if dimension == 'time':
        return 'MCS'
    spec = _DIMENSIONS.get(dimension)
    return spec[0] if spec else ''


def to_display(value, dimension, display_unit=None):
    """Convert a sim-unit value to its physical/display value. Non-numbers pass through."""
    if not _is_number(value):
        return value
    return value * factor(dimension, display_unit)


def to_model_units(value, dimension, display_unit=None):
    """Convert a physical/display value back to sim units (for writing Parameters.py).

    Non-numbers pass through unchanged.
    """
    if not _is_number(value):
        return value
    return value / factor(dimension, display_unit)


def convert_range(range_tuple, dimension, display_unit=None):
    """Convert a (min, max) range from sim units to display units (for the info panel)."""
    if range_tuple is None:
        return None
    lo, hi = range_tuple
    return (to_display(lo, dimension, display_unit), to_display(hi, dimension, display_unit))
