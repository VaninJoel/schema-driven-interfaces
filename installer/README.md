# Desktop installers (non-developer distribution)

A **single double-click installer** per OS that bundles everything — a private
Python distribution, the CompuCell3D + analysis environment, both GUI apps, the
V-Cornea model data, and all Python packages. End users download one file, run
it, and get desktop / Start-menu shortcuts. No conda, no git, no terminal, no
`conda activate`.

## Why conda-pack (and not constructor)

CompuCell3D 4.7.0's conda packages **do not resolve against conda-forge alone** —
a fresh solve fails. The only reason `conda env create -f environment.yml` works
is that conda silently pulls ~7 low-level packages (`glib`, `libxml2`,
`tifffile`, `libhwloc`, `pcre2`, …) from Anaconda's `defaults` channel to bridge
the gap. Any tool that *re-solves* the environment (e.g. `constructor`) therefore
can't reproduce it.

So instead of re-solving, we **pack the exact, already-working environment** with
[`conda-pack`](https://conda.github.io/conda-pack/) and wrap it in a
self-extracting installer. The installer ships the same bytes we test.

> **Licensing note.** Because the environment includes a few packages from
> Anaconda's `defaults` channel, redistribution is subject to Anaconda's Terms
> of Service (generally fine for academic/individual use; a paid license is
> required for large organizations). If clean public redistribution is needed,
> the alternative is a conda-forge-only CompuCell3D build — not currently
> available for 4.7.0.

## What gets produced

| OS      | Artifact                                          | User action                       |
|---------|---------------------------------------------------|-----------------------------------|
| Linux   | `SchemaDrivenInterfaces-Linux-x86_64.sh`          | `bash <file>.sh` → desktop entry  |
| macOS   | `SchemaDrivenInterfaces-macOS-<arch>.sh`          | `bash <file>.sh` → `.command` on Desktop |
| Windows | `SchemaDrivenInterfaces-Windows-x86_64.zip`       | extract → double-click `install.bat` → Start-menu shortcut |

Filenames carry no version, so the README's `releases/latest/download/<name>`
links keep working across releases; the version is the release tag.

The Linux/macOS installers are [makeself](https://makeself.io/) self-extracting
archives (one double-click file). The Windows installer is currently a `.zip`
the user extracts and runs `install.bat` from — robust and dependency-free; a
single-file `.exe` (NSIS/Inno Setup) is a planned follow-up.

## Building

Each installer must be built **on its own OS**, so build it on each platform you
want to ship and attach the files in `installer/dist/` to a GitHub Release by
hand. For the OS you're on:

```bash
# one-time build tools (makeself on Linux/macOS; 7zip on Windows — makeself
# has no Windows build)
conda install -n base -c conda-forge conda-pack makeself -y   # Linux/macOS
# conda install -n base -c conda-forge conda-pack 7zip -y      # Windows

# Linux / macOS
bash installer/build.sh
# Windows
installer\build.bat
```

Each `build` script (1) creates the conda env from `../environment.yml`,
(2) reinstalls the two wrapper packages non-editable so they're relocatable,
(3) `conda-pack`s the env, (4) stages the app code + model data, and (5) wraps
it all — together with `install.sh`/`install.bat` — into one self-extracting
installer in `installer/dist/`.

`stage/` and `dist/` are build artifacts and are git-ignored.

## How the installer behaves on the user's machine

`install.sh` / `install.bat` (bundled inside the self-extracting file) runs after
extraction and:

1. unpacks the environment to a per-user prefix (default `~/SchemaDrivenInterfaces`
   on Unix, `%LOCALAPPDATA%\SchemaDrivenInterfaces` on Windows — no admin rights);
2. runs `conda-unpack` to repair the relocated prefixes;
3. installs the app code + model data under `<prefix>/share/sdi/payload/`
   (sibling layout preserved, so the GUIs' relative path lookups keep working);
4. writes `vcornea-gui` / `angio-gui` launchers and desktop / Start-menu shortcuts.

The GUIs launch CompuCell3D with their own bundled interpreter
(`sys.executable`), so nothing depends on a conda env being registered or active.

## Validated

The Linux path is validated end to end: build → self-extracting `.sh` → install
to a clean prefix → `conda-unpack` → launchers + shortcuts created → GUI builds
and a headless CompuCell3D simulation runs and produces output — all with no
conda activation. The macOS/Windows scripts mirror this.

## Known follow-ups

- **Code signing / notarization.** Unsigned installers trip Windows SmartScreen
  and macOS Gatekeeper. Add an Authenticode cert (Windows) and Apple Developer ID
  + `notarytool` (macOS) to the build before public distribution.
- **Size.** ~1.2 GB compressed per installer (CompuCell3D + Qt + SciPy stack).
