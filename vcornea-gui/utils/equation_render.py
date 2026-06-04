"""Render LaTeX equations to cached PNGs for display in the Qt info panel.

QTextBrowser cannot typeset LaTeX/MathJax, so we pre-render each equation to a
PNG via matplotlib's `mathtext` (a LaTeX subset — no external LaTeX install) and
embed it as <img>. Images are cached by content hash under `.cache/equations/`.

`render_latex_png` returns the cache-relative filename (so the dialog can set it
as a QTextBrowser search path and reference images by bare name), or `None` when
matplotlib is unavailable or the LaTeX uses constructs outside mathtext's subset
(e.g. `\\begin{cases}`) — in which case the caller shows the LaTeX source instead.
"""
import hashlib
import struct
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "equations"


def _png_width(path):
    """Read a PNG's pixel width from its IHDR header (no PIL dependency)."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">I", head[16:20])[0]
    except Exception:
        pass
    return 0


def render_latex_png(latex, fontsize=13, dpi=140):
    """LaTeX string -> cached PNG. Returns (filename, width_px) or (None, 0) on failure.

    fontsize is modest so equations don't dominate the panel; the caller caps the
    displayed width to fit the window.
    """
    key = hashlib.md5(f"{latex}|{fontsize}|{dpi}".encode("utf-8")).hexdigest()[:16]
    fname = f"{key}.png"
    path = CACHE_DIR / fname
    if path.exists():
        return fname, _png_width(path)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None, 0
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fig = None
    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${latex}$", fontsize=fontsize)
        fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.12, facecolor="white")
        plt.close(fig)
        return fname, _png_width(path)
    except Exception:
        if fig is not None:
            try:
                plt.close(fig)
            except Exception:
                pass
        try:
            if path.exists():
                path.unlink()  # don't leave a partial/corrupt file
        except Exception:
            pass
        return None, 0
