"""Where runs go by default: never inside an installed copy's application files.

The installers replace the application folder on every reinstall, so an
installed GUI must default to the user's Documents folder. A source checkout
keeps using the app's own (git-ignored) experiments/ folder.
"""
from pathlib import Path

from PyQt5.QtCore import QStandardPaths

APP_DIRS = {'vcornea': 'vcornea-gui', 'angio': 'angio-gui'}


def test_source_checkout_uses_app_experiments(gui):
    app = APP_DIRS[gui.name]
    got = gui.main_window.default_output_dir(app)
    assert got == gui.cfg['gui_dir'].absolute() / 'experiments'


def test_installed_copy_uses_documents(gui, tmp_path, monkeypatch):
    # The installed layout: <prefix>/share/sdi/payload/<app>/gui/main_window.py, no .git.
    app = APP_DIRS[gui.name]
    fake = tmp_path / 'share' / 'sdi' / 'payload' / app / 'gui' / 'main_window.py'
    monkeypatch.setattr(gui.main_window, '__file__', str(fake))
    got = gui.main_window.default_output_dir(app)
    docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
    assert got == docs / 'SchemaDrivenInterfaces' / app / 'experiments'
    assert tmp_path not in got.parents
