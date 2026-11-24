"""Plot renderers for V-Cornea analysis, drawn onto a caller-supplied matplotlib
Figure (so they embed in the Qt FigureCanvas).

Two families, both driven by analysis_data.AnalysisDataset:
  * paper_*    — faithful reproductions of the published figures (Fig 7 / Fig 8).
  * enhanced_* — the richer GUI2-derived analyses (modes, stats, injury-centering,
                 scaling).

Time is ALWAYS days or hours (never MCS): data Time is hours (→ /24 for days);
metadata SimTime/InjuryTime are already days.
"""
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from analysis_data import CELL_TYPES, CELL_COLORS

try:
    from scipy.stats import probplot
    from scipy import stats as _spstats
    _HAS_SCIPY = True
except Exception:
    _HAS_SCIPY = False


def _unit_label(unit):
    return "Days" if unit == 'days' else "Hours"


def _combo_concat(df_list):
    return pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()


def _default_stable_day(ds):
    """Start of the analysis window for histogram/Q-Q/statistics views (days).

    Without an injury: 40% of the run, after which the tissue is treated as at
    steady state. WITH an injury the window starts at the injury time, so it
    covers damage and recovery — it is a post-injury window, not a stable phase,
    and is labelled as such (see window_label)."""
    end = ds.sim_time_days or 30
    return (ds.injury_time_days or end * 0.4) if ds.has_injury else end * 0.4


def window_label(ds, stable_day):
    """What the analysis window is, in words, for a title or caption."""
    end = ds.sim_time_days
    span = f"day {stable_day:g} to " + (f"day {end:g}" if end else "the end of the run")
    if ds.has_injury:
        return f"post-injury window, {span} (damage and recovery; not a steady state)"
    return f"steady-state window, {span}"


def _combos(ds, combo):
    if combo is not None:
        return [combo]
    return list(ds.count_data.keys())


def _short_combo_labels(ds, keys):
    """Turn long combo names into short tick labels for bar/box/heatmap axes.

    When every combination differs only in one swept parameter (names like
    'SLS Concentration=750.0'), return just the values ('750', '1500') plus the
    shared parameter name (used as an axis/title label). Otherwise fall back to
    truncated names. Returns (labels, shared_param_name_or_None)."""
    names = [ds.combo_names.get(k, k) for k in keys]
    if names and all('=' in n for n in names):
        lhs = {n.split('=', 1)[0].strip() for n in names}
        if len(lhs) == 1:
            param = lhs.pop()
            vals = []
            for n in names:
                v = n.split('=', 1)[1].strip()
                try:
                    fv = float(v)
                    v = str(int(fv)) if fv.is_integer() else f"{fv:g}"
                except ValueError:
                    pass
                vals.append(v)
            return vals, param
    return [(n[:16] + '…') if len(n) > 17 else n for n in names], None


def _set_combo_xticks(ax, x, labels):
    """Apply short combo labels, rotating only when they are genuinely long."""
    long = any(len(str(l)) > 6 for l in labels)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=30 if long else 0,
                       ha='right' if long else 'center', fontsize=8)


# ---------------------------------------------------------------- PAPER FIGURES

PAPER_COLORS = ['#55ffff', '#0055ff', '#ffbe99', '#ff007f']  # Superficial, Wing, Basal, Stem

# Literature reference ranges for tissue thickness / top position (Vanin 2025,
# Fig 8 caption + Discussion). Limbal = Pink, Central = Gray.
#   Top position:  Limbal 83.0 ± 14.3 µm [84];  Central 55.0 ± 3.0 µm [83]
#   Thickness:     Limbal ~80–85 µm     [84];  Central ~48–55 µm    [83]
REF_LIMBAL_TOP = (83.0, 14.3)     # (mean, sd) µm  — top position, ref [84]
REF_CENTRAL_TOP = (55.0, 3.0)     # (mean, sd) µm  — top position, ref [83]
REF_LIMBAL_THICK = (80.0, 85.0)   # (lo, hi) µm    — CET, Francoz et al. [84]
REF_CENTRAL_THICK = (48.0, 55.0)  # (lo, hi) µm    — CET, Liang et al. [83]
REF_PINK = '#ff9ec4'              # limbal
REF_GRAY = '#b0b0b0'              # central
REF_LIMBAL_CET_LABEL = "Limbal CET (Francoz et al.)"
REF_CENTRAL_CET_LABEL = "Central CET (Liang et al.)"


def _tconv(series, unit):
    return series / 24.0 if unit == 'days' else series  # data Time is hours


def paper_count(fig, ds, combo=None, unit='days', stable_day=None):
    """Faithful port of Plot Scripts/plot_manager.py:plot_count (Fig 7 / 10):
    longitudinal mean + per-replicate traces, per-type histograms overlaid across
    replicates, and a combined Q-Q plot. Time in days."""
    fig.clear()
    combo = combo or (list(ds.count_data)[0] if ds.count_data else None)
    df_list = ds.count_data.get(combo, [])
    if not df_list:
        fig.text(0.5, 0.5, "No cell-count data", ha='center'); return
    stable_day = _default_stable_day(ds) if stable_day is None else stable_day
    max_h = (ds.sim_time_days or (max(d['Time'].max() for d in df_list) / 24.0)) * 24.0
    stable_h = stable_day * 24.0
    hist_alpha = 0.5 if len(df_list) <= 2 else 0.075

    gs = fig.add_gridspec(4, 2)
    ax_long = fig.add_subplot(gs[0, :])
    hist_axes = [fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1]),
                 fig.add_subplot(gs[2, 0]), fig.add_subplot(gs[2, 1])]
    ax_qq = fig.add_subplot(gs[3, :])

    combined = _combo_concat(df_list)
    combined = combined[combined['Time'] <= max_h]
    combined_stable = combined[combined['Time'] >= stable_h]
    mean_data = combined.groupby('Time').mean(numeric_only=True).reset_index()
    cols = [c for c in CELL_TYPES if c in mean_data.columns]

    for i, col in enumerate(cols):
        color = PAPER_COLORS[i]
        ax_long.plot(_tconv(mean_data['Time'], unit), mean_data[col], label=f"Mean {col}", color=color, lw=2)
        # per-replicate stable histograms
        ax_h = hist_axes[i]
        all_stable = np.concatenate([d[(d['Time'] >= stable_h) & (d['Time'] <= max_h)][col].values
                                     for d in df_list]) if df_list else np.array([])
        if len(all_stable):
            edges = np.arange(int(all_stable.min()) - 0.5, int(all_stable.max()) + 1.5, 1)
            for d in df_list:
                sd = d[(d['Time'] >= stable_h) & (d['Time'] <= max_h)]
                ax_h.hist(sd[col], bins=edges, color=color, alpha=hist_alpha)
        ax_h.grid(True, lw=0.1)
        ax_h.set_title(f"Variation of {col}-Cell Number in Time and Between Replicates", fontsize=9)
        ax_h.set_xlabel("Number of Cells per Time"); ax_h.set_ylabel("Frequency")
        # Q-Q
        if _HAS_SCIPY and col in combined_stable and len(combined_stable[col]) > 1:
            probplot(combined_stable[col], dist="norm", plot=ax_qq)

    # per-replicate longitudinal traces
    for d in df_list:
        fd = d[d['Time'] < max_h]
        for i, col in enumerate(cols):
            ax_long.plot(_tconv(fd['Time'], unit), fd[col], color=PAPER_COLORS[i], alpha=0.075, lw=2)

    if _HAS_SCIPY:
        lines = ax_qq.get_lines()
        for i in range(0, min(len(lines), len(cols) * 2), 2):
            lines[i].set_color(PAPER_COLORS[i // 2]); lines[i].set_alpha(0.25)
            lines[i].set_label(cols[i // 2])
            if i + 1 < len(lines):
                lines[i + 1].set_color('black'); lines[i + 1].set_linestyle('dashed')
    ax_qq.set_title("Combined Q-Q Plots"); ax_qq.grid(True, lw=0.1); ax_qq.legend(fontsize=7)

    ax_long.axvline(_tconv(stable_h, unit) if unit == 'hours' else stable_day,
                    color='black', linestyle='dashed', lw=1, label="Stability Time")
    ax_long.set_title("Longitudinal Cell Count")
    ax_long.set_xlabel(f"Time ({_unit_label(unit)})"); ax_long.set_ylabel("Number of Cells")
    ax_long.grid(True, lw=0.1); ax_long.legend(loc='center right', fontsize=8)
    fig.suptitle(ds.combo_names.get(combo, combo), fontsize=10)
    fig.tight_layout()


def paper_thickness(fig, ds, combo=None, unit='days', stable_day=None):
    """Faithful port of Plot Scripts/plot_manager.py:plot_thickness (Fig 8):
    per-X-bin tissue TOP POSITION over time, and stable boxplots of both top
    position (blue) and thickness=Height-membrane (red) across X (µm). A bin the
    model records as Height 0 (no epithelium left) has thickness 0, not negative."""
    import seaborn as sns  # noqa: F401 (kept for parity; palette below uses mpl)
    fig.clear()
    combo = combo or (list(ds.thickness_data)[0] if ds.thickness_data else None)
    df_list = ds.thickness_data.get(combo, [])  # raw Height (voxels)
    bin_memb = ds.membrane_bins
    if not df_list or bin_memb is None:
        fig.text(0.5, 0.5, "No thickness data", ha='center'); return
    stable_day = _default_stable_day(ds) if stable_day is None else stable_day
    stable_h = stable_day * 24.0

    combined = _combo_concat(df_list)
    bins = sorted(int(b) for b in combined['Bin'].unique())
    palette = sns.color_palette("colorblind", len(bins))  # paper palette
    cmap = {b: palette[i] for i, b in enumerate(bins)}
    bins_size = 200 // len(bins)
    bin_x = {b: (b * bins_size + (bins_size - 1) / 2.0) for b in bins}  # voxels

    ax0, ax1 = fig.subplots(2)
    # individual replicate traces (top position = Height*2 µm)
    for d in df_list:
        for b in bins:
            bd = d[d['Bin'] == b]
            ax0.plot(_tconv(bd['Time'], unit), bd['Height'] * 2, alpha=0.075, lw=1, color=cmap[b])
    mean_bin = combined.groupby(['Time', 'Bin'])['Height'].mean().reset_index()
    bin_actual, bin_relative, x_um = [], [], []
    for b in bins:
        bm = mean_bin[mean_bin['Bin'] == b]
        ax0.plot(_tconv(bm['Time'], unit), bm['Height'] * 2, lw=1, color=cmap[b],
                 label=f"x {b*bins_size*2}-{(b+1)*bins_size*2} µm")
        stable_b = combined[(combined['Bin'] == b) & (combined['Time'] >= stable_h)]
        th_b = ((stable_b['Height'] - bin_memb.get(b, 10.0)) * 2).clip(lower=0.0)   # thickness µm
        bin_actual.append(th_b.mean())
        bin_relative.append(stable_b['Height'].mean() * 2)                            # top position µm
        pos = bin_x[b] * 2
        x_um.append(pos)

        def _bp(values, face):  # paper boxplot styling: thin black lines, faint fliers
            ax1.boxplot(values, positions=[pos], widths=6, patch_artist=True,
                        boxprops=dict(facecolor=face, color='black', linewidth=0.5),
                        medianprops=dict(color='black', linewidth=0.5),
                        whiskerprops=dict(color='black', linewidth=0.5),
                        capprops=dict(color='black', linewidth=0.5),
                        flierprops=dict(marker='.', markerfacecolor=face, markersize=1,
                                        markeredgewidth=0.5, alpha=0.5))
        _bp(th_b, 'tab:red')                                               # thickness
        _bp(stable_b['Height'] * 2, 'tab:blue')                            # top position

    # NOTE: literature reference lines (REF_*_TOP) intentionally omitted for now —
    # they are meaningful for control runs but not injury runs. Re-add here later
    # if desired (dash-dot Min/Max lines per paper Fig 8 middle).

    ax0.axvline(stable_day if unit == 'days' else stable_h, color='black', linestyle='dashed', lw=1,
                label="Window start" + (" (injury)" if ds.has_injury else " (stability time)"))
    ax0.set_title("Longitudinal Variation of Tissue Top Position")
    ax0.set_xlabel(f"Time ({_unit_label(unit)})"); ax0.set_ylabel("Vertical Position (µm)")
    ax0.grid(True, lw=0.3); ax0.legend(title="Bins", fontsize=6, ncol=2, loc='lower right')

    # NOTE: literature CET reference rectangles (REF_*_THICK) intentionally omitted
    # for now — meaningful for control runs but not injury runs. Re-add here later
    # (region-confined pink/gray rectangles per paper Fig 8 bottom).

    ax1.plot(x_um, bin_actual, color='tab:red', linestyle='dotted', lw=1, label="Tissue Thickness")
    ax1.plot(x_um, bin_relative, color='tab:blue', linestyle='dotted', lw=1, label="Tissue Top Position")
    ax1.set_title("Tissue Top Position and Thickness Across Sections — "
                  + window_label(ds, stable_day), fontsize=9)
    if getattr(ds, 'membrane_is_fallback', False):
        fig.text(0.5, 0.005, "WARNING: " + ds.membrane_source, ha='center', fontsize=7,
                 color='red', wrap=True)
    ax1.set_xlabel("Horizontal Position (µm)"); ax1.set_ylabel("Vertical Position / Thickness (µm)")
    # boxplot positions are µm — set explicit ticks so the x-axis reads in µm
    # (otherwise matplotlib mislabels them as 1..N).
    ax1.set_xticks([round(p) for p in x_um])
    ax1.set_xticklabels([str(round(p)) for p in x_um])
    ax1.set_xlim(min(x_um) - 12, max(x_um) + 12)
    ax1.grid(True, lw=0.3); ax1.legend(fontsize=7)
    fig.suptitle(ds.combo_names.get(combo, combo), fontsize=10)
    fig.tight_layout()


# -------------------------------------------------------------- ENHANCED PLOTS

def _apply_scale(mean_df, std_df, scale, baseline_df):
    if scale == 'Percentage':
        total = mean_df[CELL_TYPES].sum(axis=1)
        for ct in CELL_TYPES:
            if ct in mean_df:
                mean_df[ct] = mean_df[ct] / total * 100
                std_df[ct] = std_df[ct] / total * 100
    elif scale == 'PctChangeFromBaseline' and baseline_df is not None and len(baseline_df):
        for ct in CELL_TYPES:
            if ct in mean_df:
                base = baseline_df[ct].mean()
                if base > 0:
                    mean_df[ct] = (mean_df[ct] - base) / base * 100
                    std_df[ct] = std_df[ct] / base * 100


def enhanced_count(fig, ds, mode='individual', combo=None, unit='days',
                   injury_centered=False, scale='Absolute', stable_day=None):
    fig.clear()
    stable_day = _default_stable_day(ds) if stable_day is None else stable_day
    ic = injury_centered and ds.has_injury
    ylabel = {'Absolute': 'Cell count', 'Percentage': 'Percentage (%)',
              'PctChangeFromBaseline': '% change from baseline'}.get(scale, 'Cell count')

    if mode == 'comparison':
        axes = fig.subplots(2, 2)
        for ci, ct in enumerate(CELL_TYPES):
            ax = axes[ci // 2, ci % 2]
            for combo_key, df_list in ds.count_data.items():
                cm = _combo_concat(df_list); cm['t'] = ds.time_axis(cm, unit, ic)
                md = cm.groupby('t').mean(numeric_only=True).reset_index()
                sd = cm.groupby('t').std(numeric_only=True).reset_index()
                base = cm[cm['t'] < 0] if ic else cm[cm['t'] < (stable_day if unit == 'days' else stable_day*24)]
                _apply_scale(md, sd, scale, base)
                if ct in md:
                    ax.plot(md['t'], md[ct], lw=2, label=ds.combo_names.get(combo_key, combo_key))
                    ax.fill_between(md['t'], md[ct]-sd[ct], md[ct]+sd[ct], alpha=0.1)
            if ic:
                ax.axvline(0, color='red', ls='--', lw=1.5)
            ax.set_title(f"{ct}"); ax.set_xlabel(f"{'Δ ' if ic else ''}Time ({_unit_label(unit)})")
            ax.set_ylabel(ylabel); ax.grid(True, alpha=0.2); ax.legend(fontsize=7)
        fig.suptitle("Combination comparison"); fig.tight_layout(); return

    if mode == 'statistics':
        _enhanced_stats(fig, ds, stable_day, unit); return

    # individual (one combo)
    combo = combo or (list(ds.count_data)[0] if ds.count_data else None)
    df_list = ds.count_data.get(combo, [])
    if not df_list:
        fig.text(0.5, 0.5, "No data", ha='center'); return
    ax = fig.add_subplot(1, 1, 1)
    ax_w = ax.twinx()
    cm = _combo_concat(df_list); cm['t'] = ds.time_axis(cm, unit, ic)
    md = cm.groupby('t').mean(numeric_only=True).reset_index()
    sd = cm.groupby('t').std(numeric_only=True).reset_index()
    base = cm[cm['t'] < 0] if ic else cm[cm['t'] < (stable_day if unit == 'days' else stable_day*24)]
    _apply_scale(md, sd, scale, base)
    for ct in CELL_TYPES:
        if ct not in md:
            continue
        tgt = ax_w if ct == 'Wing' else ax
        tgt.plot(md['t'], md[ct], color=CELL_COLORS[ct], lw=2, label=ct)
        tgt.fill_between(md['t'], md[ct]-sd[ct], md[ct]+sd[ct], color=CELL_COLORS[ct], alpha=0.08)
        for df in df_list:
            t = ds.time_axis(df, unit, ic)
            tgt.plot(t, df[ct], color=CELL_COLORS[ct], alpha=0.12, lw=0.6)
    if ic:
        ax.axvline(0, color='red', ls='--', lw=2, label='Injury')
    ax.set_title(f"Cell Dynamics — {ds.combo_names.get(combo, combo)}")
    ax.set_xlabel(f"{'Days relative to injury' if ic else 'Time (' + _unit_label(unit) + ')'}")
    ax.set_ylabel(f"{ylabel} (non-wing)"); ax_w.set_ylabel(f"Wing {ylabel.lower()}")
    ax.grid(True, alpha=0.2)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax_w.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc='best')
    fig.tight_layout()


def replicate_window_means(ds, stable_day):
    """{combo: {'Total': [mean per replicate], <cell type>: [...], 'CV': [per replicate]}}.

    One number per REPLICATE: its mean over the analysis window (and, for CV, its
    own variability over time in that window). Replicates are the independent
    units; the hourly samples of one run are not. Pooling every hourly sample of
    every replicate into one group and testing those inflates n by three orders
    of magnitude and turns any difference into a vanishing p-value.
    """
    cutoff_h = stable_day * 24                       # data Time is hours
    out = {}
    for combo, df_list in ds.count_data.items():
        rows = {'Total': [], 'CV': [], **{ct: [] for ct in CELL_TYPES}}
        for df in df_list:
            w = df[df['Time'] >= cutoff_h]
            if w.empty:
                continue
            total = w[[c for c in CELL_TYPES if c in w]].sum(axis=1)
            rows['Total'].append(float(total.mean()))
            rows['CV'].append(float(total.std() / total.mean()) if total.mean() else np.nan)
            for ct in CELL_TYPES:
                if ct in w:
                    rows[ct].append(float(w[ct].mean()))
        out[combo] = rows
    return out


def _enhanced_stats(fig, ds, stable_day, unit):
    axes = fig.subplots(2, 2)
    stats_by = replicate_window_means(ds, stable_day)
    keys = list(stats_by)
    labels, param = _short_combo_labels(ds, keys)
    x = np.arange(len(keys))
    axlabel = param or "Combination"
    n_txt = ", ".join(f"n={len(stats_by[k]['Total'])}" for k in keys)
    # per-replicate window means of the total count: every replicate is one dot
    ax = axes[0, 0]
    for i, k in enumerate(keys):
        v = stats_by[k]['Total']
        ax.scatter(np.full(len(v), i), v, s=22, alpha=0.75, zorder=2)
        if v:
            ax.hlines(np.mean(v), i - 0.25, i + 0.25, color='black', lw=1.5, zorder=3)
    ax.set_title("Total count, mean per replicate"); ax.set_ylabel("Cells")
    _set_combo_xticks(ax, x, labels); ax.set_xlabel(axlabel)
    # temporal CV of each replicate, averaged over replicates
    cv = [np.nanmean(stats_by[k]['CV']) if stats_by[k]['CV'] else np.nan for k in keys]
    axes[0, 1].bar(x, cv, color='#7f8c8d')
    axes[0, 1].axhline(0.1, color='red', ls='--', label='CV=0.1')
    _set_combo_xticks(axes[0, 1], x, labels); axes[0, 1].set_xlabel(axlabel)
    axes[0, 1].set_title("Variability over time within a run\n(CV per replicate, averaged)")
    axes[0, 1].legend(fontsize=7)
    # mean per type (mean of replicate means)
    w = 0.8 / len(CELL_TYPES)
    for i, ct in enumerate(CELL_TYPES):
        means = [np.mean(stats_by[k][ct]) if stats_by[k][ct] else 0 for k in keys]
        axes[1, 0].bar(x + i*w, means, w, label=ct, color=CELL_COLORS[ct])
    _set_combo_xticks(axes[1, 0], x + w*1.5, labels); axes[1, 0].set_xlabel(axlabel)
    axes[1, 0].set_title("Mean count by type"); axes[1, 0].legend(fontsize=7)
    # pairwise tests on the per-replicate means
    ax = axes[1, 1]
    testable = _HAS_SCIPY and len(keys) > 1 and all(len(stats_by[k]['Total']) >= 2 for k in keys)
    if testable:
        n = len(keys); pm = np.ones((n, n))
        for i, a in enumerate(keys):
            for j, b in enumerate(keys):
                if i != j:
                    try:
                        pm[i, j] = _spstats.mannwhitneyu(
                            stats_by[a]['Total'], stats_by[b]['Total'],
                            alternative='two-sided')[1]
                    except Exception:
                        pm[i, j] = np.nan
        im = ax.imshow(pm, cmap='RdYlGn_r', vmin=0, vmax=0.1)
        ax.set_xticks(range(n)); ax.set_yticks(range(n))
        ax.set_xticklabels(labels, rotation=30 if any(len(str(l)) > 6 for l in labels) else 0, fontsize=8)
        ax.set_yticklabels(labels, fontsize=8)
        for i in range(n):
            for j in range(n):
                if i != j and np.isfinite(pm[i, j]):
                    ax.text(j, i, f"{pm[i, j]:.3f}", ha='center', va='center', fontsize=7)
        fig.colorbar(im, ax=ax)
        ax.set_title("Pairwise p (Mann-Whitney on replicate means;\ndescriptive, uncorrected)",
                     fontsize=9)
    else:
        ax.axis('off')
        ax.text(0.5, 0.5, "Pairwise tests need ≥2 combinations\nwith ≥2 replicates each",
                ha='center', va='center')
    ttl = f"Cross-combination statistics — {window_label(ds, stable_day)}\n" \
          f"one value per replicate ({n_txt})"
    if param:
        ttl += f" — swept: {param}"
    if ds.metadata_varies():
        ttl += "\nNOTE: injury time / injury switch / length differ between combinations; " \
               "one window is applied to all"
    fig.suptitle(ttl, fontsize=9); fig.tight_layout()


LIMBAL_BIN = 0                 # Bin 0 = Limbus
CENTRAL_BINS = (4, 5, 6, 7, 8, 9)  # post-transition (paper leaves Bins 1–3 unshaded)


def enhanced_thickness(fig, ds, combo=None, unit='days', injury_centered=False, stable_day=None):
    """Cross-combination thickness comparison (the betterment the paper view can't
    show). Two panels — limbal vs central epithelial thickness over time, one line
    per combination (replicate mean) with a ±1 SD band across replicates.

    NOTE: literature reference bands intentionally omitted for now (meaningful for
    control runs but not injury runs); re-add via REF_*_THICK if desired."""
    fig.clear()
    if not ds.thickness_um:
        fig.text(0.5, 0.5, "No thickness data", ha='center'); return
    ic = injury_centered and ds.has_injury

    ax_limbal, ax_central = fig.subplots(2, 1, sharex=True)
    regions = [
        (ax_limbal, "Limbal (Bin 0)", [LIMBAL_BIN]),
        (ax_central, "Central / peripheral (Bins 4–9)", list(CENTRAL_BINS)),
    ]
    for ax, title, region_bins in regions:
        for combo_key, df_list in ds.thickness_um.items():
            # each replicate's region thickness (mean over the region's bins) per time,
            # then mean ± SD across replicates
            reps = []
            for df in df_list:
                d = df[df['Bin'].isin(region_bins)]
                if not d.empty:
                    d = d.assign(t=ds.time_axis(d, unit, ic))
                    reps.append(d.groupby('t')['Thickness'].mean())
            if not reps:
                continue
            per_t = pd.concat(reps, axis=1)
            mean, sd = per_t.mean(axis=1), per_t.std(axis=1)
            name = ds.combo_names.get(combo_key, combo_key)
            line, = ax.plot(mean.index, mean.values, lw=2, label=f"{name} (n={len(reps)})")
            if len(reps) > 1:
                ax.fill_between(mean.index, mean - sd, mean + sd, color=line.get_color(),
                                alpha=0.15, lw=0)
        if ic:
            ax.axvline(0, color='red', ls='--', lw=1.5)
        ax.set_title(title)
        ax.set_ylabel("Thickness (µm)")
        ax.grid(True, alpha=0.2)
        ax.legend(fontsize=7)
    ax_central.set_xlabel(f"{'Δ ' if ic else ''}Time ({_unit_label(unit)})")
    fig.suptitle("Epithelial thickness — combination comparison by region")
    fig.tight_layout()


# ------------------------------------------------------------------ SURFACTANT

_SURF_COL = 'Total Amount'


def _surf_series(df):
    """Return (time_hours, amount) for a surfactant replicate, robust to col name."""
    col = _SURF_COL if _SURF_COL in df.columns else next(
        (c for c in df.columns if c != 'Time'), None)
    return df['Time'].astype(float).values, df[col].astype(float).values if col else None


def surfactant_compare(fig, ds, unit='days', injury_centered=False):
    """Overlay total surfactant amount over time for every combination
    (mean across replicates + faint replicate traces)."""
    fig.clear()
    if not ds.surfactant_data:
        fig.text(0.5, 0.5, "No surfactant data", ha='center'); return
    ic = injury_centered and ds.has_injury
    ax = fig.add_subplot(1, 1, 1)
    for combo_key, df_list in ds.surfactant_data.items():
        cm = _combo_concat(df_list)
        col = _SURF_COL if _SURF_COL in cm.columns else next((c for c in cm.columns if c != 'Time'), None)
        if col is None:
            continue
        cm['t'] = ds.time_axis(cm, unit, ic)
        md = cm.groupby('t')[col].mean().reset_index()
        sd = cm.groupby('t')[col].std().reset_index()
        line, = ax.plot(md['t'], md[col], lw=2, label=ds.combo_names.get(combo_key, combo_key))
        ax.fill_between(md['t'], md[col] - sd[col], md[col] + sd[col], color=line.get_color(), alpha=0.12)
        for df in df_list:  # faint per-replicate traces
            t = ds.time_axis(df, unit, ic)
            ax.plot(t, df[col], color=line.get_color(), alpha=0.12, lw=0.7)
    if ic:
        ax.axvline(0, color='red', ls='--', lw=2, label='Injury')
    ax.set_title("Surfactant load over time — combination comparison")
    ax.set_xlabel(f"{'Δ ' if ic else ''}Time ({_unit_label(unit)})")
    ax.set_ylabel("Total surfactant amount (arb. units)")
    ax.grid(True, alpha=0.2); ax.legend(fontsize=8)
    fig.tight_layout()


def _surf_metrics(t_hours, amount, unit):
    """Peak amount, time-to-peak, and clearance half-life (peak → half-peak)."""
    if amount is None or len(amount) == 0:
        return None
    amount = np.asarray(amount, float); t = np.asarray(t_hours, float)
    ipeak = int(np.argmax(amount)); peak = amount[ipeak]; tpeak = t[ipeak]
    half_life = np.nan
    if peak > 0:
        after = np.where((t > tpeak) & (amount <= peak / 2.0))[0]
        if len(after):
            half_life = t[after[0]] - tpeak
    conv = (lambda x: x / 24.0) if unit == 'days' else (lambda x: x)
    return {'peak': peak, 'tpeak': conv(tpeak),
            'half_life': conv(half_life) if not np.isnan(half_life) else np.nan}


def surfactant_stats(fig, ds, unit='days'):
    """Peak amount, time-to-peak, and clearance half-life per combination."""
    fig.clear()
    if not ds.surfactant_data:
        fig.text(0.5, 0.5, "No surfactant data", ha='center'); return
    keys, peaks, tpeaks, halfs = [], [], [], []
    for combo_key, df_list in ds.surfactant_data.items():
        # average the metrics across replicates
        ms = [m for m in (_surf_metrics(*_surf_series(df), unit) for df in df_list) if m]
        if not ms:
            continue
        keys.append(combo_key)
        peaks.append(np.nanmean([m['peak'] for m in ms]))
        tpeaks.append(np.nanmean([m['tpeak'] for m in ms]))
        halfs.append(np.nanmean([m['half_life'] for m in ms]))
    if not keys:
        fig.text(0.5, 0.5, "No surfactant data", ha='center'); return
    labels, param = _short_combo_labels(ds, keys)
    axlabel = param or "Combination"
    ut = _unit_label(unit)
    ax1, ax2, ax3 = fig.subplots(1, 3)
    x = np.arange(len(keys))
    for ax, vals, color, title in [
        (ax1, peaks, '#c0392b', "Peak amount (arb.)"),
        (ax2, tpeaks, '#e67e22', f"Time to peak ({ut})"),
        (ax3, halfs, '#2980b9', f"Clearance half-life ({ut})"),
    ]:
        ax.bar(x, vals, color=color)
        ax.set_title(title, fontsize=10)
        _set_combo_xticks(ax, x, labels)
        ax.set_xlabel(axlabel)
        ax.grid(True, alpha=0.2)
    ttl = "Surfactant kinetics (mean over replicates)"
    if param:
        ttl += f" — swept: {param}"
    fig.suptitle(ttl)
    fig.tight_layout()
