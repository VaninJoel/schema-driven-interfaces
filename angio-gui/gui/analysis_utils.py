"""
Analysis utilities for angiogenesis simulation data.

This module provides functions for loading and analyzing zarr-formatted
simulation data, computing network metrics, and extracting statistics.

Author: GUI Implementation
Date: 2025
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Handle zarr import - it's required for analysis
try:
    import zarr
    ZARR_AVAILABLE = True
except ImportError:
    ZARR_AVAILABLE = False
    print("Warning: zarr not installed. Analysis features will be limited.")

# Handle scipy import for network analysis
try:
    from scipy.ndimage import label  # noqa: F401  (availability probe)
    from vivarium_angio.utils import network_metrics as _nm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy not installed. Network metrics will be limited.")


class ExperimentData:
    """
    Container for a single experiment's data and metadata.
    """

    def __init__(self, exp_dir: Path):
        """
        Initialize by loading experiment data from directory.

        Args:
            exp_dir: Path to experiment directory containing data.zarr and run_metadata.json
        """
        self.exp_dir = Path(exp_dir)
        self.exp_name = self.exp_dir.name

        # Load metadata
        self.metadata = self._load_metadata()
        self.parameters = self.metadata.get('parameters', {})

        # Load zarr store
        self.zarr_path = self.exp_dir / 'data.zarr'
        self.root = None
        self.timesteps = []

        if ZARR_AVAILABLE and self.zarr_path.exists():
            try:
                self.root = zarr.open(str(self.zarr_path), mode='r')
                self.timesteps = sorted([int(k) for k in self.root.keys() if k.isdigit()])
            except Exception as e:
                print(f"Error opening zarr store: {e}")

    def _load_metadata(self) -> Dict:
        """Load run_metadata.json."""
        metadata_file = self.exp_dir / 'run_metadata.json'
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                return json.load(f)
        return {}

    def get_data(self, timestep: int) -> Optional[np.ndarray]:
        """
        Load data for a specific timestep.

        Args:
            timestep: MCS timestep to load

        Returns:
            numpy array of shape [x, y, z, 3] or None if not available
        """
        if self.root is None:
            return None

        timestep_str = str(timestep)
        if timestep_str not in self.root:
            return None

        try:
            data = self.root[timestep_str]['data'][:]
            return data
        except Exception as e:
            print(f"Error loading data for timestep {timestep}: {e}")
            return None

    def get_cell_types(self, timestep: int) -> Optional[np.ndarray]:
        """Get cell type field (channel 0)."""
        data = self.get_data(timestep)
        return data[:,:,:,0] if data is not None else None

    def get_cell_ids(self, timestep: int) -> Optional[np.ndarray]:
        """Get cell ID field (channel 1)."""
        data = self.get_data(timestep)
        return data[:,:,:,1] if data is not None else None

    def get_vegf_field(self, timestep: int) -> Optional[np.ndarray]:
        """Get VEGF concentration field (channel 2)."""
        data = self.get_data(timestep)
        return data[:,:,:,2] if data is not None else None

    def get_vegf_global_range(self) -> tuple:
        """
        Compute global VEGF min and max across all timesteps.

        Returns:
            (vmin, vmax) tuple for consistent colorbar scaling
        """
        vmin = float('inf')
        vmax = float('-inf')

        for timestep in self.timesteps:
            vegf = self.get_vegf_field(timestep)
            if vegf is not None:
                vmin = min(vmin, vegf.min())
                vmax = max(vmax, vegf.max())

        # Handle edge case where no data was found
        if vmin == float('inf'):
            vmin, vmax = 0.0, 1.0

        return (float(vmin), float(vmax))


def compute_network_metrics(cell_types: np.ndarray, cell_ids: np.ndarray = None) -> Dict:
    """
    Network measures of one snapshot of the cell-type field (1 = EC, 0 = Medium).

    Every measure is defined in vivarium_angio.utils.network_metrics
    (METRIC_DEFINITIONS, METRIC_UNITS) and computed on the model's lattice:
    4-neighbour connectivity, periodic in x and y — the same code the archive
    exporter uses. The result always carries every key of NETWORK_METRIC_KEYS, in
    that order; a measure that cannot be computed is None (scipy missing, no cell
    ids given) or NaN (undefined for this field).
    """
    metrics = {key: None for key in _nm.NETWORK_METRIC_KEYS} if SCIPY_AVAILABLE else {}
    binary = cell_types == 1
    ec_pixels = int(np.sum(binary))
    metrics['total_ec_pixels'] = ec_pixels
    metrics['cell_density'] = float(ec_pixels / cell_types.size) if cell_types.size else 0.0

    if SCIPY_AVAILABLE:
        cluster_sizes = _nm.cluster_sizes(binary)
        metrics['num_clusters'] = len(cluster_sizes)
        metrics['largest_cluster_size'] = int(max(cluster_sizes)) if cluster_sizes else 0
        metrics['mean_cluster_size'] = float(np.mean(cluster_sizes)) if cluster_sizes else 0.0
        metrics['fragmentation_index'] = (len(cluster_sizes) / ec_pixels) if ec_pixels else 0.0
        metrics['connectivity_index'] = (max(cluster_sizes) / ec_pixels) if ec_pixels else 0.0
        metrics['network_perimeter'] = _nm.network_perimeter(binary)
        metrics['compactness'] = float(_nm.compactness(binary))
    else:
        for key in ('num_clusters', 'largest_cluster_size', 'mean_cluster_size',
                    'fragmentation_index', 'connectivity_index', 'network_perimeter',
                    'compactness', 'num_cells', 'mean_cell_size', 'std_cell_size'):
            metrics.setdefault(key, None)

    if cell_ids is not None:
        ids, sizes = np.unique(cell_ids[cell_ids > 0], return_counts=True)   # 0 = medium
        metrics['num_cells'] = int(len(ids))
        metrics['mean_cell_size'] = float(np.mean(sizes)) if len(ids) else 0.0
        metrics['std_cell_size'] = float(np.std(sizes)) if len(ids) else 0.0

    return metrics


def metric_label(key: str) -> str:
    """'Largest Cluster Size (lattice sites)' — a metric name with its unit."""
    name = key.replace('_', ' ').title()
    unit = _nm.METRIC_UNITS.get(key) if SCIPY_AVAILABLE else None
    return f"{name} ({unit})" if unit else name


def metric_definition(key: str) -> str:
    """The one-sentence definition of a metric, or '' if none is recorded."""
    return (_nm.METRIC_DEFINITIONS.get(key, '') if SCIPY_AVAILABLE else '')


def compute_vegf_statistics(vegf_field: np.ndarray) -> Dict:
    """
    Compute VEGF field statistics.

    Args:
        vegf_field: 3D array of VEGF concentrations

    Returns:
        dict with statistics: min, max, mean, std, median, percentile_95
    """
    return {
        'min': float(vegf_field.min()),
        'max': float(vegf_field.max()),
        'mean': float(vegf_field.mean()),
        'std': float(vegf_field.std()),
        'median': float(np.median(vegf_field)),
        'percentile_95': float(np.percentile(vegf_field, 95)),
    }


def analyze_time_series(exp_data: ExperimentData) -> Dict:
    """
    Analyze all timesteps in an experiment.

    Args:
        exp_data: ExperimentData object

    Returns:
        dict with time series data for each metric
    """
    time_series = {
        'timesteps': exp_data.timesteps,
        'network_metrics': [],
        'vegf_stats': [],
    }

    for timestep in exp_data.timesteps:
        # Network metrics
        cell_types = exp_data.get_cell_types(timestep)
        cell_ids = exp_data.get_cell_ids(timestep)
        if cell_types is not None:
            metrics = compute_network_metrics(cell_types, cell_ids=cell_ids)
            time_series['network_metrics'].append(metrics)

        # VEGF statistics
        vegf = exp_data.get_vegf_field(timestep)
        if vegf is not None:
            stats = compute_vegf_statistics(vegf)
            time_series['vegf_stats'].append(stats)

    return time_series


def export_metrics_to_csv(time_series: Dict, output_path: Path):
    """
    Export time series metrics to CSV file.

    Args:
        time_series: Dict from analyze_time_series()
        output_path: Path to output CSV file
    """
    import csv

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        # Write header
        header = ['Timestep']

        # Add network metric headers
        if time_series['network_metrics']:
            for key in time_series['network_metrics'][0].keys():
                header.append(f'network_{key}')

        # Add VEGF stat headers
        if time_series['vegf_stats']:
            for key in time_series['vegf_stats'][0].keys():
                header.append(f'vegf_{key}')

        writer.writerow(header)

        # Write data rows
        for i, timestep in enumerate(time_series['timesteps']):
            row = [timestep]

            # Add network metrics, in the header's column order
            if i < len(time_series['network_metrics']):
                metrics = time_series['network_metrics'][i]
                row.extend([metrics.get(k, '') for k in time_series['network_metrics'][0].keys()])

            # Add VEGF stats
            if i < len(time_series['vegf_stats']):
                stats = time_series['vegf_stats'][i]
                row.extend([stats.get(k, '') for k in stats.keys()])

            writer.writerow(row)

    print(f"Metrics exported to {output_path}")


def find_experiments(output_dir: Path) -> List[Path]:
    """
    Find all experiment directories in output folder.

    Args:
        output_dir: Path to search for experiments

    Returns:
        List of experiment directory paths
    """
    experiments = []

    output_dir = Path(output_dir)
    if not output_dir.exists():
        return experiments

    # Runs live at any depth (each launch has its own timestamped folder), so
    # search recursively rather than one level down. Only runs whose record says
    # they completed are offered: a failed, timed-out or cancelled run keeps its
    # partial Zarr for diagnosis (and in its archive), but replaying it here
    # beside completed runs would present it as a result.
    for zarr_path in output_dir.rglob('data.zarr'):
        item = zarr_path.parent
        if zarr_path.is_dir() and run_status(item) == 'success':
            experiments.append(item)

    return sorted(experiments)


def run_status(exp_dir: Path):
    """'success' / 'failed' / 'timed_out' / 'cancelled', or None if unrecorded."""
    exp_dir = Path(exp_dir)
    if (exp_dir / 'cancelled.json').exists():
        return 'cancelled'
    try:
        meta = json.loads((exp_dir / 'run_metadata.json').read_text())
    except Exception:
        return None
    status = meta.get('simulation_status')
    if status:
        return status
    return 'success' if (meta.get('execution') or {}).get('success') else 'failed'


def completed_run_problem(exp_dir: Path) -> Optional[str]:
    """Why a directory may NOT be analysed as a result, or None if it may.

    Every way of bringing a run into the analysis window goes through this, not
    only the experiment list: a failed, timed-out or cancelled run keeps a partial
    trajectory that looks like any other once loaded."""
    exp_dir = Path(exp_dir)
    if not (exp_dir / 'data.zarr').exists():
        return "no data.zarr"
    status = run_status(exp_dir)
    if status is None:
        return "no run record (run_metadata.json), so it cannot be shown to have completed"
    if status != 'success':
        return f"run recorded as {status}; its trajectory is partial"
    return None


# Recorded on every run but not part of the model's parameterization.
_NON_MODEL_PARAM_KEYS = frozenset((
    'exp_name', 'store_path', 'creator', 'random_seed', 'random_seed_origin',
    '_schema_fingerprint', 'parameter_scan', 'scan_point', 'combination_index',
    'total_combinations', 'replicate_id', 'total_replicates', 'parent_experiment_id',
))


def replicate_set_problem(exp_data_list) -> Optional[str]:
    """Why a set of runs may NOT be summarised as replicates of one condition, or
    None if it may. Replicates share every model parameter and are compared at the
    same final step."""
    finals = {e.exp_name: (e.timesteps[-1] if e.timesteps else None) for e in exp_data_list}
    if len(set(finals.values())) > 1:
        return ("the runs end at different steps ("
                + ", ".join(f"{n}: {t}" for n, t in finals.items())
                + "), so their final values are not comparable")

    def model_params(e):
        return {k: v for k, v in (e.parameters or {}).items() if k not in _NON_MODEL_PARAM_KEYS}
    first = model_params(exp_data_list[0])
    differing = sorted({k for e in exp_data_list[1:]
                        for k in set(first) | set(model_params(e))
                        if first.get(k) != model_params(e).get(k)})
    if differing:
        return ("the runs differ in " + ", ".join(differing)
                + ", so they are not replicates of one condition")
    return None


def detect_cell_boundaries(cell_ids: np.ndarray) -> np.ndarray:
    """
    Detect cell boundaries from cell ID field.

    Args:
        cell_ids: 3D array of cell IDs

    Returns:
        Binary array where 1 = boundary, 0 = interior/medium
    """
    # Take 2D slice for processing
    cell_ids_2d = cell_ids[:, :, 0]

    # Create boundary mask
    boundaries = np.zeros_like(cell_ids_2d, dtype=bool)

    # Check 4-connectivity neighbors for different cell IDs
    for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
        # Shift array in each direction
        shifted = np.roll(np.roll(cell_ids_2d, dx, axis=0), dy, axis=1)

        # Mark pixels where neighbor has different ID
        boundaries |= (cell_ids_2d != shifted) & (cell_ids_2d > 0)

    return boundaries.astype(np.uint8)


def compare_replicates_statistics(exp_data_list: List[ExperimentData], metric_name: str) -> Dict:
    """
    Compare a specific metric across replicates with statistical tests.

    Args:
        exp_data_list: List of ExperimentData objects (replicates)
        metric_name: Name of metric to compare (e.g., 'cell_density', 'num_clusters')

    Returns:
        dict with mean, std, sem, and optionally statistical test results
    """
    # Collect final timestep values for the metric
    values = []

    for exp_data in exp_data_list:
        time_series = analyze_time_series(exp_data)

        if time_series['network_metrics']:
            # Get value from last timestep
            last_metrics = time_series['network_metrics'][-1]
            if metric_name in last_metrics and last_metrics[metric_name] is not None:
                values.append(last_metrics[metric_name])

    if not values:
        return {'error': f'No data found for metric: {metric_name}'}

    values = np.array(values)

    stats = {
        'n': len(values),
        'mean': float(np.mean(values)),
        'std': float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        'sem': float(np.std(values, ddof=1) / np.sqrt(len(values))) if len(values) > 1 else 0.0,
        'min': float(np.min(values)),
        'max': float(np.max(values)),
        'median': float(np.median(values)),
    }

    # Add confidence interval
    if len(values) > 1:
        try:
            from scipy import stats as scipy_stats
            confidence = 0.95
            ci = scipy_stats.t.interval(confidence, len(values)-1,
                                        loc=stats['mean'],
                                        scale=stats['sem'])
            stats['ci_95_lower'] = float(ci[0])
            stats['ci_95_upper'] = float(ci[1])
        except:
            pass

    return stats


def compare_parameter_sweep(exp_groups: Dict[str, List[ExperimentData]], metric_name: str) -> Dict:
    """
    Compare metric across parameter values with replicates.

    Args:
        exp_groups: Dict mapping parameter value to list of ExperimentData objects
                    e.g., {'jem_2.0': [exp1, exp2, exp3], 'jem_4.0': [exp4, exp5, exp6]}
        metric_name: Name of metric to compare

    Returns:
        dict with statistics for each parameter value and ANOVA results
    """
    results = {}
    all_groups = []
    param_values = []

    for param_value, exp_list in exp_groups.items():
        # Get statistics for this parameter value
        stats = compare_replicates_statistics(exp_list, metric_name)
        results[param_value] = stats

        # Collect for ANOVA
        values = []
        for exp_data in exp_list:
            time_series = analyze_time_series(exp_data)
            if time_series['network_metrics']:
                last_metrics = time_series['network_metrics'][-1]
                if metric_name in last_metrics and last_metrics[metric_name] is not None:
                    values.append(last_metrics[metric_name])

        all_groups.append(values)
        param_values.append(param_value)

    # Perform ANOVA if we have multiple groups
    if len(all_groups) >= 2 and all(len(g) > 0 for g in all_groups):
        try:
            from scipy import stats as scipy_stats
            f_stat, p_value = scipy_stats.f_oneway(*all_groups)
            results['anova'] = {
                'f_statistic': float(f_stat),
                'p_value': float(p_value),
                'significant': p_value < 0.05
            }
        except:
            results['anova'] = {'error': 'ANOVA failed'}

    return results


def create_animation_frames(exp_data: ExperimentData,
                            show_cells: bool = True,
                            show_vegf: bool = True,
                            show_boundaries: bool = False,
                            vegf_vmin: float = None,
                            vegf_vmax: float = None) -> List[np.ndarray]:
    """
    Create frames for animation export.

    Args:
        exp_data: ExperimentData object
        show_cells: Whether to show cell field
        show_vegf: Whether to show VEGF field
        show_boundaries: Whether to show cell boundaries
        vegf_vmin: Minimum value for VEGF colorbar (auto if None)
        vegf_vmax: Maximum value for VEGF colorbar (auto if None)

    Returns:
        List of RGB images (numpy arrays) for each timestep
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
    except ImportError:
        print("matplotlib required for creating animation frames")
        return []

    frames = []

    for timestep in exp_data.timesteps:
        # Create figure for this frame
        fig, axes = plt.subplots(1, 2 if (show_cells and show_vegf) else 1,
                                figsize=(12 if (show_cells and show_vegf) else 6, 6))

        if not (show_cells and show_vegf):
            axes = [axes]

        ax_idx = 0

        # Plot cells
        if show_cells:
            ax = axes[ax_idx]
            ax_idx += 1

            cell_types = exp_data.get_cell_types(timestep)
            if cell_types is not None:
                cell_slice = cell_types[:, :, 0]

                # Custom colormap
                colors = ['white', '#8B0000']
                cmap = ListedColormap(colors)

                ax.imshow(cell_slice, cmap=cmap, interpolation='nearest')

                # Overlay boundaries if requested
                if show_boundaries:
                    cell_ids = exp_data.get_cell_ids(timestep)
                    if cell_ids is not None:
                        boundaries = detect_cell_boundaries(cell_ids)
                        # Use contour lines for sub-pixel thickness (0.1 linewidth)
                        ax.contour(boundaries, levels=[0.5], colors='black',
                                  linewidths=0.1, linestyles='solid')

                ax.set_title(f'Cell Field - Step {timestep}')
                ax.set_xlabel('X')
                ax.set_ylabel('Y')
                ax.axis('tight')

        # Plot VEGF
        if show_vegf:
            ax = axes[ax_idx]

            vegf_field = exp_data.get_vegf_field(timestep)
            if vegf_field is not None:
                vegf_slice = vegf_field[:, :, 0]

                # Use locked colorbar range if provided
                im = ax.imshow(vegf_slice, cmap='viridis', interpolation='bilinear',
                              vmin=vegf_vmin, vmax=vegf_vmax)
                ax.set_title(f'VEGF Field - Step {timestep}')
                ax.set_xlabel('X')
                ax.set_ylabel('Y')
                ax.axis('tight')

                # Add colorbar
                fig.colorbar(im, ax=ax, label='VEGF Concentration', fraction=0.046)

        fig.tight_layout()

        # Convert figure to RGB array
        fig.canvas.draw()

        # Use buffer_rgba() for modern matplotlib compatibility
        # Convert RGBA to RGB by dropping alpha channel
        width, height = fig.canvas.get_width_height()
        buffer = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
        buffer = buffer.reshape(height, width, 4)  # RGBA format
        rgb_buffer = buffer[:, :, :3]  # Drop alpha channel to get RGB

        frames.append(rgb_buffer)

        plt.close(fig)

    return frames


def export_animation_gif(frames: List[np.ndarray], output_path: Path, fps: int = 5):
    """
    Export animation frames as GIF.

    Args:
        frames: List of RGB images (numpy arrays)
        output_path: Path to output GIF file
        fps: Frames per second
    """
    try:
        import imageio
    except ImportError:
        raise ImportError("imageio required for GIF export. Install with: pip install imageio")

    duration = 1000 / fps  # Duration in milliseconds

    imageio.mimsave(output_path, frames, duration=duration, loop=0)
    print(f"Animation exported to {output_path}")


def export_animation_mp4(frames: List[np.ndarray], output_path: Path, fps: int = 5):
    """
    Export animation frames as MP4 video.

    Args:
        frames: List of RGB images (numpy arrays)
        output_path: Path to output MP4 file
        fps: Frames per second
    """
    try:
        import imageio
    except ImportError:
        raise ImportError("imageio required for MP4 export. Install with: pip install imageio imageio-ffmpeg")

    imageio.mimsave(output_path, frames, fps=fps, codec='libx264', pixelformat='yuv420p')
    print(f"Animation exported to {output_path}")