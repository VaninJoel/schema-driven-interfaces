"""
Analysis utilities for vCornea CellFate simulation data.

This module provides helpers for loading CSV/Parquet outputs and
organizing them by output category.

Author: GUI Implementation
Date: 2026
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# Output categories produced by the canonical paper_version model. The former
# cellfate-branch categories (maboss_states, cell_states, injury_tracking,
# injury_edge, memb_disruption) were removed — paper_version never writes them.
OUTPUT_PATTERNS = {
    'cell_count': 'cell_count_*.csv',
    'thickness': 'thickness_rep*.parquet',
    'surfactant': 'surfactant_*.csv',
}


def find_output_files(exp_dir: Path) -> Dict[str, List[Path]]:
    """
    Return output files by category, searched recursively.

    Handles every run layout produced by the GUI:
    1. Files directly in exp_dir/                    (legacy)
    2. exp_dir/replicate_*/                           (single run, N replicates)
    3. exp_dir/<combo>/replicate_*/                   (parameter sweep)
    rglob covers all of these regardless of nesting depth.
    """
    exp_dir = Path(exp_dir)
    outputs: Dict[str, List[Path]] = {}

    for name, pattern in OUTPUT_PATTERNS.items():
        files = list(exp_dir.rglob(pattern))
        outputs[name] = sorted(set(files))  # Remove duplicates and sort

    return outputs


def load_table(path: Path) -> pd.DataFrame:
    """Load a CSV or Parquet table."""
    path = Path(path)
    if path.suffix.lower() == '.parquet':
        return pd.read_parquet(path)
    return pd.read_csv(path)


def detect_time_column(df: pd.DataFrame) -> Optional[str]:
    """Try to find a time column for plotting."""
    candidates = ['Time', 'time', 'mcs', 'MCS', 'Hour', 'hour', 'hours']
    for name in candidates:
        if name in df.columns:
            return name
    return None


def numeric_columns(df: pd.DataFrame) -> List[str]:
    """Return numeric column names."""
    return [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


class ExperimentData:
    """Container for one experiment directory."""

    def __init__(self, exp_dir: Path):
        self.exp_dir = Path(exp_dir)
        self.outputs = find_output_files(self.exp_dir)

    def categories(self) -> List[str]:
        return [name for name, files in self.outputs.items() if files]

    def files_for(self, category: str) -> List[Path]:
        return self.outputs.get(category, [])

    def load(self, category: str, index: int = 0) -> Tuple[Optional[pd.DataFrame], Optional[Path]]:
        files = self.files_for(category)
        if not files or index >= len(files):
            return None, None
        path = files[index]
        return load_table(path), path
