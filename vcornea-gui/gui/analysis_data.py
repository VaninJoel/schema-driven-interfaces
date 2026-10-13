"""Unified analysis dataset loader for V-Cornea runs.

Replicate-aware, hours-native, metadata-driven. Shared by both the paper-faithful
plots and the enhanced (GUI2-derived) plots so neither re-implements data loading.

Time conventions (verified against real outputs):
  * Data files (cell_count, thickness, surfactant) store `Time` in HOURS.
  * run_metadata.json stores SimTime / InjuryTime in DAYS (schema is day-stored).
  * => MCS never appears in analysis. Display is days (Time/24) or hours.

Thickness:
  * `Height` is the top-cell vertical centre-of-mass in VOXELS, per X-bin.
  * true thickness (µm) = (Height - membrane_baseline[bin]) * 2, with the
    per-x membrane baseline from the shipped paper membrane_height.csv.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

CELL_TYPES = ['Superficial', 'Wing', 'Basal', 'Stem']
CELL_COLORS = {'Superficial': '#55ffff', 'Wing': '#0055ff', 'Basal': '#ffbe99', 'Stem': '#ff007f'}
HOURS_PER_DAY = 24.0
VOXEL_TO_UM = 2.0
N_BINS = 10
DOMAIN_X_VOXELS = 200
_MEMBRANE_CSV = Path(__file__).resolve().parent.parent / "analysis_data" / "membrane_height.csv"


class AnalysisDataset:
    """Loads + groups one experiment directory's count/thickness outputs."""

    def __init__(self, exp_dir):
        self.exp_dir = Path(exp_dir)
        (self.count_files, self.thickness_files,
         self.surfactant_files, self.metadata_files) = self._collect()
        self.membrane_bins = self._load_membrane()        # {bin: voxels}
        # metadata (days; MCS never used)
        self.sim_time_days = None
        self.injury_time_days = None
        self.has_injury = False
        self.injury_type = None
        self._load_metadata()
        # grouped {combo: [df per replicate]}
        self.count_data = self._group(self.count_files)
        self.thickness_data = self._group(self.thickness_files)
        self.thickness_um = self._to_thickness_um(self.thickness_data)
        self.surfactant_data = self._group(self.surfactant_files)  # {combo: [dfs]}, Time in hours
        self.combo_names = self._combo_names()

    # ---- discovery / grouping ----
    def _collect(self):
        """Find output files, keeping only those from runs that succeeded.

        Excluded (and listed in self.excluded_runs, dir -> status):
          * anything inside a vcornea_sim_* workspace — the per-replicate CC3D
            project copy, which would otherwise surface as a phantom combination;
          * replicates whose record says failed / timed_out / cancelled. Their
            partial outputs stay on disk and in their archives for diagnosis, but
            plotting them beside completed runs would present them as results.
        Runs with no status record (older versions) are kept.
        """
        base = self.exp_dir
        self.excluded_runs = {}
        status_cache = {}

        def keep(p):
            rel = p.relative_to(base).parts[:-1]
            if any(part.startswith('vcornea_sim_') for part in rel):
                return False
            run_dir = p.parent
            if run_dir not in status_cache:
                status_cache[run_dir] = self._run_status(run_dir)
            status = status_cache[run_dir]
            if status not in (None, 'success'):
                self.excluded_runs[str(run_dir)] = status
                return False
            return True

        count = [str(p) for p in base.rglob("cell_count_*.csv") if keep(p)]
        thick = [str(p) for p in base.rglob("thickness_rep_*.parquet") if keep(p)]
        surf = [str(p) for p in base.rglob("surfactant_*.csv") if keep(p)]
        meta = [p for p in base.rglob("run_metadata.json") if keep(p)]
        if self.excluded_runs:
            print(f"[analysis] excluded {len(self.excluded_runs)} unsuccessful run(s): "
                  + ", ".join(f"{Path(d).name}={s}" for d, s in sorted(self.excluded_runs.items())))
        return count, thick, surf, meta

    def _run_status(self, run_dir):
        """'success' / 'failed' / 'timed_out' / 'cancelled', or None if unrecorded.

        The replicate's own run_metadata.json status wins (a replicate that
        finished before its batch was stopped is still a completed run). Without
        one, a cancelled.json / timed_out.json marker between run_dir and the
        analysed experiment root marks it interrupted.
        """
        run_dir = Path(run_dir)
        meta_path = run_dir / 'run_metadata.json'
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                meta = {}
            if meta.get('simulation_status'):
                return meta['simulation_status']
            if meta.get('simulation_success') is False:
                return 'failed'
        for d in [run_dir, *run_dir.parents]:
            for marker, status in (('cancelled.json', 'cancelled'), ('timed_out.json', 'timed_out')):
                if (d / marker).exists():
                    return status
            if d == self.exp_dir:
                break
        return None

    @staticmethod
    def _combo_key(path):
        """Combo = the dir above replicate_*/, else the file's parent dir."""
        p = Path(path)
        return p.parent.parent.name if p.parent.name.startswith('replicate_') else p.parent.name

    def _group(self, files):
        grouped = {}
        for f in files:
            try:
                df = pd.read_parquet(f) if f.lower().endswith('.parquet') else pd.read_csv(f)
            except Exception as e:
                print(f"[analysis] skip {f}: {e}")
                continue
            grouped.setdefault(self._combo_key(f), []).append(df)
        return grouped

    # ---- membrane baseline ----
    def _load_membrane(self):
        bins = {i: [] for i in range(N_BINS)}
        bin_size = DOMAIN_X_VOXELS / N_BINS
        try:
            raw = pd.read_csv(_MEMBRANE_CSV, header=None)
            for x, h in zip(raw[0].values, raw[1].values):
                idx = int(x // bin_size)
                if idx in bins:
                    bins[idx].append(h)
            return {i: (float(np.mean(v)) if v else 10.0) for i, v in bins.items()}
        except Exception as e:
            print(f"[analysis] membrane_height.csv unavailable ({e}); using flat 10-voxel baseline")
            return {i: 10.0 for i in range(N_BINS)}

    def _to_thickness_um(self, thickness_data):
        """Per combo/replicate, add a 'Thickness' column in µm (membrane-subtracted)."""
        out = {}
        for combo, df_list in thickness_data.items():
            conv = []
            for df in df_list:
                if 'Height' not in df.columns or 'Bin' not in df.columns:
                    continue
                d = df.copy()
                base = d['Bin'].map(lambda b: self.membrane_bins.get(int(b), 10.0))
                d['Thickness'] = (d['Height'] - base) * VOXEL_TO_UM
                conv.append(d)
            if conv:
                out[combo] = conv
        return out

    # ---- metadata ----
    def _load_metadata(self):
        # Prefer a metadata file that actually carries the run config (the
        # replicate-level run_metadata.json); the batch-level one lacks it.
        meta = None
        for mf in self.metadata_files:
            try:
                m = json.load(open(mf))
            except Exception:
                continue
            if 'simulation_config' in m or 'key_parameters' in m:
                meta = m
                break
        if meta is None:
            return
        cfg = meta.get('simulation_config', {})
        kp = meta.get('key_parameters', {})
        self.has_injury = bool(cfg.get('has_injury', kp.get('IsInjury', False)))
        self.injury_type = cfg.get('injury_type')
        # DAYS in the new metadata (schema is day-stored); never MCS.
        self.sim_time_days = cfg.get('sim_time', kp.get('SimTime'))
        self.injury_time_days = kp.get('InjuryTime')

    def _combo_names(self):
        """Label each combo by the swept parameter's value (sweeps), else dir name.

        The swept parameter set is the union of parameter_changes keys across all
        combos; each combo is labelled by that parameter's key_parameters value
        (so the base combo, whose parameter_changes is empty, is still labelled).
        """
        combo_meta = {}   # combo_key -> metadata dict (prefer one with key_parameters)
        swept = set()
        for mf in self.metadata_files:
            try:
                meta = json.load(open(mf))
            except Exception:
                continue
            ck = self._combo_key(mf)
            if 'key_parameters' in meta and ('key_parameters' not in combo_meta.get(ck, {})):
                combo_meta[ck] = meta
            for p in (meta.get('parameter_changes') or {}):
                swept.add(p)
        names = {}
        all_combos = set(self.count_data) | set(self.thickness_um) | set(self.surfactant_data)
        for ck in all_combos:
            kp = combo_meta.get(ck, {}).get('key_parameters', {})
            parts = [f"{p.replace('_', ' ')}={kp.get(p)}" for p in sorted(swept) if p in kp]
            names[ck] = ", ".join(parts) if parts else ck
        return names

    # ---- time helpers (HOURS native; never MCS) ----
    @staticmethod
    def hours_to_days(t_hours):
        return np.asarray(t_hours) / HOURS_PER_DAY

    def time_axis(self, df, unit='days', injury_centered=False):
        """Return the Time column converted to the requested display unit."""
        t = df['Time'].astype(float)
        t = t / HOURS_PER_DAY if unit == 'days' else t  # hours stay as-is
        if injury_centered and self.has_injury and self.injury_time_days is not None:
            offset = self.injury_time_days if unit == 'days' else self.injury_time_days * HOURS_PER_DAY
            t = t - offset
        return t

    def replicate_count(self, combo):
        return len(self.count_data.get(combo, []))

    def summary(self):
        return {
            'combos': list(self.count_data.keys()),
            'replicates': {c: self.replicate_count(c) for c in self.count_data},
            'has_injury': self.has_injury,
            'injury_type': self.injury_type,
            'sim_time_days': self.sim_time_days,
            'injury_time_days': self.injury_time_days,
            'has_thickness': bool(self.thickness_um),
        }
