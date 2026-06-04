"""Context help for the analysis plot panel.

Explains, for every configuration (kind × family × mode × options): what the
plot shows, how to read it, which controls to use, and what a healthy result
looks like. Surfaced by the ⓘ button in PlotPanel via build_help(...).

The text is intentionally interpretive — it tells the operator not just what is
drawn but what to expect physiologically and how to act on what they see.
"""

# ---------------------------------------------------------------------------
# Per (kind, family, mode): a dict with four labelled blocks. Any block may be
# omitted. Rendered in order: shows → read → use → expect.
# ---------------------------------------------------------------------------
_PLOT_TEXT = {

    # ---- CELL COUNTS · PAPER -------------------------------------------------
    ('count', 'paper', None): {
        'shows':
            "A faithful reproduction of the paper's cell-count figure (Fig 7 for "
            "homeostasis, Fig 10 for the post-injury response), drawn from <i>your</i> "
            "run's data so you can compare it side-by-side with the publication.",
        'read':
            "<b>Top — Longitudinal Cell Count:</b> one bold line per cell type is the "
            "mean across replicates; the faint lines behind it are the individual "
            "replicates; the dashed vertical line marks the <i>stability time</i> (when "
            "the tissue is treated as having reached steady state). "
            "<b>Middle (2×2) — histograms:</b> the distribution of each type's count "
            "during the stable phase, with every replicate overlaid — a tall narrow peak "
            "means a tightly regulated population, a wide or multi-peaked spread means it "
            "drifts. <b>Bottom — Combined Q-Q:</b> each type's stable counts plotted "
            "against a normal distribution; points hugging the black dashed line indicate "
            "normally-distributed (well-regulated) counts.",
        'use':
            "This is the view to use when you want to <b>check a single run against the "
            "published behaviour</b>. Pick the combination with the Run selector, set "
            "Time to Days, and read the plateau heights off the top panel. Use the "
            "toolbar to save a PNG for a report.",
        'expect':
            "In an undisturbed homeostatic run the four means settle onto flat plateaus "
            "(roughly Superficial ≈ 47, Wing ≈ 128, Basal ≈ 32, Stem ≈ 5 in the "
            "reference geometry) and stay there; the histograms are narrow and the Q-Q "
            "points lie close to the line. Sloping lines, fat histograms, or Q-Q points "
            "curving away mean the tissue has not equilibrated — extend SimTime or check "
            "the parameters.",
    },

    # ---- CELL COUNTS · ENHANCED · INDIVIDUAL --------------------------------
    ('count', 'enhanced', 'individual'): {
        'shows':
            "One combination in detail — the cell-population dynamics of a single "
            "scenario, with replicate spread made explicit.",
        'read':
            "The bold line is the mean across replicates and the shaded band is ±1 "
            "standard deviation; the faint thin lines are the individual replicates. "
            "<b>Wing is drawn on the right-hand axis</b> because it is ~3× the other "
            "layers and would otherwise flatten them — read Wing against the right scale, "
            "the other three against the left.",
        'use':
            "Use this to inspect <b>how one scenario behaves</b> and how reproducible it "
            "is. Select the combination with the Run selector. Turn on <i>Center on "
            "injury</i> for a wounded run to put t=0 at the wound. Switch <i>Scale</i> to "
            "Percentage or % change to emphasise composition or disruption rather than "
            "absolute numbers.",
        'expect':
            "A healthy run shows the band hugging the mean (replicates agree) and flat "
            "plateaus after the initial settling. A wide band means the replicates "
            "disagree — run more replicates or investigate stochastic instability. After "
            "an injury you should see a dip then a recovery back toward the pre-injury "
            "plateau.",
    },

    # ---- CELL COUNTS · ENHANCED · COMPARISON --------------------------------
    ('count', 'enhanced', 'comparison'): {
        'shows':
            "Every combination overlaid, so you can see how the scenarios diverge. "
            "This is a betterment over the paper, which showed scenarios on separate "
            "figures.",
        'read':
            "Four sub-panels, one per cell type. Within each, every combination is a "
            "coloured mean line with a faint ±SD band; the legend names them by the "
            "swept parameter (e.g. <i>SLS Concentration=750</i> vs <i>=1500</i>). When "
            "injury-centring is on, a red dashed line marks the wound at t=0.",
        'use':
            "This is the main <b>“difference between combinations”</b> view. Use it to "
            "answer questions like “which dose loses more basal cells, and when does it "
            "recover?”. Set Time to Days; the Run selector is ignored here (all combos "
            "are shown). Pair it with the Statistics mode to test whether the gaps you "
            "see are significant.",
        'expect':
            "If a swept parameter matters, the lines separate (e.g. a higher surfactant "
            "dose drives a deeper, slower-recovering dip). If the lines sit on top of "
            "each other, the parameter had little effect over the range you swept.",
    },

    # ---- CELL COUNTS · ENHANCED · STATISTICS --------------------------------
    ('count', 'enhanced', 'statistics'): {
        'shows':
            "Quantitative cross-combination statistics computed over the stable phase — "
            "the numbers behind the Comparison view.",
        'read':
            "<b>Total count boxplots</b> — the spread of total cells per combination. "
            "<b>Coefficient of Variation</b> — relative variability of the total; the "
            "red line at 0.1 is a rule-of-thumb stability threshold (below it = tight "
            "homeostasis). <b>Mean count by type</b> — grouped bars comparing each "
            "layer across combinations. <b>Pairwise p-value heatmap</b> — a "
            "Mann-Whitney test on the total counts for every pair; greener / lower means "
            "the two combinations differ significantly.",
        'use':
            "Use this to <b>back up a claim with statistics</b>. Read the CV bars to "
            "judge whether each run is actually at steady state, then read the heatmap to "
            "see which pairs are significantly different. Needs ≥2 combinations for the "
            "heatmap; a single run shows a placeholder there.",
        'expect':
            "Well-regulated runs sit below the CV=0.1 line. In the heatmap, combinations "
            "that you expect to behave the same (e.g. two replicate doses) should be "
            "<i>non</i>-significant (red), and genuinely different scenarios should be "
            "significant (green).",
    },

    # ---- THICKNESS · PAPER ---------------------------------------------------
    ('thickness', 'paper', None): {
        'shows':
            "A faithful reproduction of the paper's tissue-thickness figure (Fig 8), "
            "from your run's data.",
        'read':
            "<b>Top — Tissue Top Position over time:</b> the apical surface height for "
            "each horizontal X-bin (limbus → central cornea), one colour per bin; faint "
            "lines are replicates, the dashed line is the stability time. "
            "<b>Bottom — across sections (µm):</b> stable-phase boxplots versus "
            "horizontal position, where "
            "<span style='color:#1f77b4'><b>blue = top position</b></span> and "
            "<span style='color:#d62728'><b>red = tissue thickness</b></span> "
            "(top minus the basement-membrane baseline). The dotted trend lines connect "
            "the per-section means.",
        'read2':
            "Heights come from the model in voxels and are converted at "
            "<b>1 voxel = 2 µm</b>; thickness subtracts a per-section basement-membrane "
            "baseline so it reflects the epithelial layer alone.",
        'use':
            "Use this to verify the <b>limbal-to-central thickness gradient</b> and "
            "compare it against the paper. Pick a combination, set Time to Days, and read "
            "the bottom panel left-to-right across the cornea.",
        'expect':
            "The epithelium is thickest toward the limbus and thins toward the centre, "
            "and the surface is stable over time once past the stability line. A "
            "collapsing or runaway top-position trace signals a tissue-mechanics problem "
            "rather than a healthy steady state.",
    },

    # ---- THICKNESS · ENHANCED (cross-combination) ----------------------------
    ('thickness', 'enhanced', None): {
        'shows':
            "The cross-combination thickness view — what the paper figure can't show: "
            "limbal and central epithelial thickness for <i>every</i> combination on the "
            "same axes.",
        'read':
            "Two stacked panels. <b>Top — Limbal (Bin 0):</b> mean epithelial thickness "
            "of the limbal region over time, one line per combination. "
            "<b>Bottom — Central / peripheral (Bins 4–9):</b> the same for the central "
            "region. The paper's transition bins (1–3) are excluded. Thickness = "
            "top-cell position − basement-membrane baseline, in µm.",
        'use':
            "Use this to <b>compare scenarios by region</b> — e.g. does a higher "
            "surfactant dose thin the central epithelium more than the limbal? Turn on "
            "<i>Center on injury</i> to align recovery at t=0. The Run selector is "
            "ignored here (all combinations are overlaid).",
        'expect':
            "Limbal thicker than central, and stable after settling. Lines that separate "
            "show the swept parameter affects thickness; after an injury, a localised dip "
            "that recovers.",
    },

    # ---- SURFACTANT · COMPARE ------------------------------------------------
    ('surfactant', 'enhanced', 'compare'): {
        'shows':
            "Total surfactant load over time, overlaid for every combination — the "
            "“difference between doses” view for surfactant.",
        'read':
            "One line per combination is the mean total surfactant amount across "
            "replicates; the faint band is ±SD and the thin lines are individual "
            "replicates. With injury-centring on, a red dashed line marks the exposure / "
            "wound at t=0.",
        'use':
            "Use this to see <b>how much surfactant accumulates and how fast it "
            "clears</b> across scenarios. Turn on <i>Center on injury</i> to align the "
            "exposure event. Pair with the Statistics mode to quantify peak and "
            "clearance.",
        'expect':
            "Surfactant rises during exposure and then clears toward zero. A higher dose "
            "should show a higher peak and/or slower clearance; combinations that overlap "
            "experienced effectively the same load.",
    },

    # ---- SURFACTANT · STATISTICS ---------------------------------------------
    ('surfactant', 'enhanced', 'statistics'): {
        'shows':
            "Surfactant kinetics summarised per combination: how high, how fast, how "
            "persistent.",
        'read':
            "Three bar panels, one bar per combination (mean over replicates): "
            "<b>Peak amount</b> (maximum total load reached); <b>Time to peak</b> (how "
            "quickly it built up); and <b>Clearance half-life</b> (time from the peak for "
            "the load to fall to half — larger = slower clearance).",
        'use':
            "Use this to <b>rank scenarios quantitatively</b> — which dose loads the "
            "tissue most and which lingers longest. Switch the Time control to read "
            "time-to-peak and half-life in days or hours.",
        'expect':
            "Peak amount should scale with the applied dose; time-to-peak is usually "
            "short; half-life reflects clearance capacity. A very long or absent "
            "half-life (no fall to half-peak within the run) means the surfactant never "
            "cleared — worth noting.",
    },
}

# Option-specific notes appended when the control is active.
_OPTION_TEXT = {
    'injury':
        "<b>Center on injury (t=0 at the wound):</b> the time axis is shifted so the "
        "injury event sits at zero; negative times are pre-injury. This aligns the "
        "recovery phase across runs that were wounded at different times, so you compare "
        "“time since wound” rather than absolute time. Available only when the run "
        "actually includes an injury.",
    'scale_Percentage':
        "<b>Scale = Percentage:</b> each cell type is shown as a fraction of the total "
        "population at each time instead of an absolute count — useful for watching "
        "tissue <i>composition</i> shift even when the total is changing.",
    'scale_PctChangeFromBaseline':
        "<b>Scale = % change from baseline:</b> values are the percent change relative "
        "to the pre-injury (or pre-stable) baseline, so the plot emphasises the <i>size</i> "
        "of the disruption and the completeness of recovery rather than absolute numbers.",
}

# Shared concepts, shown once in a collapsible-style footer.
_GLOSSARY = (
    "<h4>Reference</h4>"
    "<ul>"
    "<li><b>Time units:</b> the model runs in Monte-Carlo steps, but plots <i>never</i> "
    "show MCS — the stored data is hourly and is displayed in Days or Hours (your choice "
    "in the Time control).</li>"
    "<li><b>Replicates:</b> independent runs of the same combination (different random "
    "seeds). Mean lines and ±SD bands aggregate across them; faint lines are the "
    "individual replicates. More replicates → more trustworthy spread.</li>"
    "<li><b>Stability time:</b> the point after which the tissue is treated as being at "
    "steady state; histogram, boxplot and statistics windows are taken from <i>after</i> "
    "this time so start-up transients don't pollute them.</li>"
    "<li><b>Length:</b> 1 voxel = 2 µm; thickness subtracts a per-section basement-"
    "membrane baseline so it reflects the epithelial layer, not absolute height.</li>"
    "</ul>"
)


def _block(d):
    """Render the ordered blocks of one _PLOT_TEXT entry."""
    order = [
        ('shows',  'What this shows'),
        ('read',   'How to read it'),
        ('read2',  None),            # continuation of "read", no heading
        ('use',    'How to use it'),
        ('expect', 'What to expect'),
    ]
    parts = []
    for key, heading in order:
        text = d.get(key)
        if not text:
            continue
        if heading:
            parts.append(f"<h4>{heading}</h4>")
        parts.append(f"<p>{text}</p>")
    return "".join(parts)


def build_help(kind, family, mode, injury_centered, scale, unit, ds):
    """Assemble an HTML explanation for the current plot configuration."""
    fam = 'paper' if family == 'paper' else 'enhanced'
    mode_keyed = fam == 'enhanced' and kind in ('count', 'surfactant')
    key = (kind, fam, mode if mode_keyed else None)
    entry = _PLOT_TEXT.get(key, {})

    data = {'count': ds.count_data, 'thickness': ds.thickness_data,
            'surfactant': ds.surfactant_data}.get(kind, ds.count_data)
    n_combos = len(data)
    reps = sorted({ds.replicate_count(c) for c in ds.count_data}) if kind == 'count' else None

    title = 'Paper figure' if fam == 'paper' else 'Enhanced'
    parts = [f"<h3>{title} — {kind.title()}</h3>"]

    # Main per-configuration body.
    body = _block(entry)
    if body:
        parts.append(body)

    # Current context line.
    parts.append(
        f"<p style='color:#34495e'><b>Right now:</b> {n_combos} combination"
        f"{'s' if n_combos != 1 else ''} loaded, time in <b>{unit}</b>"
        + (f", scale = <b>{scale}</b>" if (kind == 'count' and fam == 'enhanced' and scale) else "")
        + ".</p>"
    )

    # Replicate note tailored to this experiment.
    if reps:
        if reps == [1]:
            parts.append(
                "<p style='color:#7f8c8d'><i>This experiment has 1 replicate per "
                "combination, so the mean line coincides with the single run and the SD "
                "band is flat. Run multiple replicates to see run-to-run variability.</i></p>")
        else:
            parts.append(
                f"<p style='color:#7f8c8d'><i>Means and SD bands aggregate across "
                f"{min(reps)}–{max(reps)} replicates per combination.</i></p>")

    # Active options.
    opts = []
    if injury_centered and ds.has_injury:
        opts.append(_OPTION_TEXT['injury'])
    if kind == 'count' and fam == 'enhanced' and scale and scale != 'Absolute':
        opts.append(_OPTION_TEXT.get(f'scale_{scale}', ''))
    if opts:
        parts.append("<h4>Active options</h4>" + "".join(f"<p>{o}</p>" for o in opts if o))

    if fam == 'paper':
        parts.append(
            "<p style='color:#7f8c8d'><i>Rendered in the same style as the published "
            "figure so you can compare your run's data directly against the paper. The "
            "image is generated from your data — it is not the published figure itself.</i></p>")

    parts.append(_GLOSSARY)
    parts.append("<p style='color:#7f8c8d'><i>Tip: use the toolbar to zoom, pan and save "
                 "the plot as a PNG.</i></p>")
    return "".join(parts)
