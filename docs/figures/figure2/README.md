# Figure 2

`make_figure2.py` builds manuscript Figure 2 ("One parameter definition,
several consumers") from the running code and writes into this folder:
`panel_A.png` ... `panel_E.png`, the assembled `figure2.png` / `figure2.pdf`,
`caption.md`, and the text behind the panels (`panel_A.txt`, `panel_B.json`,
`panel_D.json`).

```bash
python docs/figures/figure2/make_figure2.py      # in the vc environment, from the repository root
```

It needs nothing outside this repository: it loads both GUIs through
`tests/gui/harness.py`, lays the windows out without showing them (on a Linux
machine with no display it uses Qt's offscreen platform) and draws panels B, C
and E from the widgets and dialogs themselves; panels A and D are printed from
`ports_schema()` and `build_parameter_audit()`. Pillow assembles the panels.
The figure is 17 cm wide with no text below 7 pt, apart from the subscripts
inside the rendered equation. The script pins font sizes and abridges long
strings (marked with `[...]` in the panels); it does not change any value.

The files here were rendered on Windows 11 (Arial and Consolas). On another
system the fonts, and therefore line breaks and panel heights, can differ.
The caption carries the schema fingerprints the panels were generated from.
