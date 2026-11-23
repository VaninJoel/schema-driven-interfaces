"""Cluster and boundary measures of the endothelial network, on the model's lattice.

One definition, used by the GUI analysis layer and by the archive exporter, so the
numbers a user sees and the numbers an archive carries cannot differ.

Conventions
-----------
* The network is analysed in the lattice plane (the model is dim_z = 1).
* Neighbourhood: the four nearest lattice neighbours (von Neumann).
* Boundaries: periodic in x and y, as the model declares them
  (`PottsCore(boundary_x="Periodic", boundary_y="Periodic")`). Two endothelial
  sites facing each other across a lattice edge are neighbours, so a cluster that
  crosses an edge is one cluster and the result does not depend on where the
  coordinate origin happens to lie. Pass `periodic=(False, False)` for the
  statistic of a cropped, non-periodic image instead.
* A boundary site is an endothelial site with at least one medium neighbour.
  `network_perimeter` is the number of boundary sites (unit: lattice sites); a
  fully occupied periodic lattice has none.

Needs numpy and scipy only.
"""
from __future__ import annotations

# Mirrors the Potts boundary conditions of AngiogenesisProcess (x, y).
ANGIO_PERIODIC = (True, True)

METRIC_DEFINITIONS = {
    'num_clusters': ('Number of connected endothelial clusters (4-neighbour '
                     'connectivity, periodic in x and y). Unit: count.'),
    'largest_cluster_size': ('Size of the largest connected endothelial cluster. '
                             'Unit: lattice sites.'),
    'cell_density': ('Fraction of lattice sites occupied by endothelial cells. '
                     'Dimensionless, 0-1.'),
    'vegf_mean': ('Mean of the VEGF field over all lattice sites. Unit: model '
                  'concentration units (not calibrated to a physical unit).'),
    'network_perimeter': ('Number of endothelial sites with at least one medium '
                          '4-neighbour (periodic in x and y). Unit: lattice sites.'),
    'total_ec_pixels': 'Number of lattice sites occupied by endothelial cells. Unit: lattice sites.',
    'mean_cluster_size': 'Mean size of the connected endothelial clusters. Unit: lattice sites.',
    'fragmentation_index': ('Number of clusters divided by the number of endothelial sites '
                            '(clusters per endothelial site). 0 when there is no endothelium.'),
    'connectivity_index': ('Fraction of endothelial sites that belong to the largest cluster. '
                           'Dimensionless, 0-1; 1 means one connected network.'),
    'compactness': ('Fraction of endothelial sites that are interior, i.e. have no medium '
                    '4-neighbour: 1 - network_perimeter / endothelial sites. Dimensionless, '
                    '0-1; near 0 for a network of thin cords, 1 for a solid mass. Undefined '
                    '(NaN) when there is no endothelium.'),
    'num_cells': 'Number of distinct cell identifiers present. Unit: cells.',
    'mean_cell_size': 'Mean number of lattice sites per cell. Unit: lattice sites.',
    'std_cell_size': 'Standard deviation of lattice sites per cell. Unit: lattice sites.',
}

# Short unit for a table cell or an axis label.
METRIC_UNITS = {
    'num_clusters': 'count',
    'largest_cluster_size': 'lattice sites',
    'cell_density': 'fraction of lattice sites',
    'vegf_mean': 'model units',
    'network_perimeter': 'lattice sites',
    'total_ec_pixels': 'lattice sites',
    'mean_cluster_size': 'lattice sites',
    'fragmentation_index': 'clusters per EC site',
    'connectivity_index': 'fraction of EC sites',
    'compactness': 'fraction of EC sites',
    'num_cells': 'cells',
    'mean_cell_size': 'lattice sites',
    'std_cell_size': 'lattice sites',
}

# The network metrics the analysis layer reports, in a fixed order: every result
# carries every key, so exported columns cannot shift between snapshots.
NETWORK_METRIC_KEYS = (
    'total_ec_pixels', 'cell_density', 'num_clusters', 'largest_cluster_size',
    'mean_cluster_size', 'fragmentation_index', 'connectivity_index',
    'network_perimeter', 'compactness', 'num_cells', 'mean_cell_size', 'std_cell_size',
)


def compactness(mask, periodic=ANGIO_PERIODIC):
    """Interior fraction of the endothelium: 1 - boundary sites / endothelial sites.

    In [0, 1]. NaN when the field holds no endothelial site. (An isoperimetric
    ratio 4*pi*A/P**2 is not used: with a boundary-SITE count as P it exceeds 1 for
    a disc and is undefined for a fully occupied lattice.)"""
    flat = planar_mask(mask)
    total = int(flat.sum())
    if total == 0:
        return float('nan')
    return 1.0 - network_perimeter(flat, periodic) / total


def planar_mask(mask):
    """Collapse a [X, Y, 1] (or deeper) boolean field to the [X, Y] lattice plane."""
    import numpy as np
    flat = np.asarray(mask).astype(bool)
    while flat.ndim > 2:
        flat = flat.squeeze(-1) if flat.shape[-1] == 1 else flat.any(axis=-1)
    return flat


def label_clusters(mask, periodic=ANGIO_PERIODIC):
    """Label 4-connected clusters of a planar mask. Returns (labels, n).

    `labels` is an int array (0 = background, 1..n = clusters). Along each
    periodic axis, clusters touching across the lattice edge are merged.
    """
    import numpy as np
    from scipy.ndimage import label
    flat = planar_mask(mask)
    lab, n = label(flat)
    if n == 0 or not any(periodic):
        return lab, int(n)

    parent = np.arange(n + 1)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for axis, wraps in enumerate(periodic[:2]):
        if not wraps or flat.shape[axis] < 2:
            continue
        first, last = np.take(lab, 0, axis=axis), np.take(lab, -1, axis=axis)
        both = (first > 0) & (last > 0)
        for a, b in set(zip(first[both].tolist(), last[both].tolist())):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

    roots = np.array([find(i) for i in range(n + 1)])
    _, compact = np.unique(roots, return_inverse=True)   # root 0 (background) -> 0
    return compact[lab], int(compact.max())


def cluster_sizes(mask, periodic=ANGIO_PERIODIC):
    """Sizes (lattice sites) of every cluster, in label order; [] when empty."""
    import numpy as np
    lab, n = label_clusters(mask, periodic)
    return np.bincount(lab.ravel(), minlength=n + 1)[1:].tolist() if n else []


def boundary_sites(mask, periodic=ANGIO_PERIODIC):
    """Boolean [X, Y] array: endothelial sites with at least one medium 4-neighbour.

    Across a non-periodic edge the outside of the lattice counts as medium.
    """
    import numpy as np
    flat = planar_mask(mask)
    interior = flat.copy()
    for axis in (0, 1):
        wraps = bool(periodic[axis]) if axis < len(periodic) else False
        for shift in (1, -1):
            neighbour = np.roll(flat, shift, axis=axis)
            if not wraps:
                edge = [slice(None), slice(None)]
                edge[axis] = 0 if shift == 1 else -1
                neighbour[tuple(edge)] = False
            interior &= neighbour
    return flat & ~interior


def network_perimeter(mask, periodic=ANGIO_PERIODIC):
    """Number of boundary sites (see `boundary_sites`)."""
    return int(boundary_sites(mask, periodic).sum())
