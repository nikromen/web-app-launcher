import sys

from web_app_launcher.constants import APP_NAME
from web_app_launcher.utils.desktop_file_manager import DesktopFileManager


def test_escape_desktop_value_strips_newlines():
    assert DesktopFileManager._escape_desktop_value("line1\nline2\r") == "line1 line2"


def test_create_desktop_file_writes_expected_content(tmp_path, sample_app, monkeypatch):
    monkeypatch.setattr("web_app_launcher.utils.desktop_file_manager.shutil.which", lambda _: None)
    manager = DesktopFileManager(tmp_path)
    manager.create_desktop_file(sample_app)

    desktop_file = manager.get_desktop_file_path(sample_app.app_uuid)
    content = desktop_file.read_text(encoding="utf-8")

    assert desktop_file.exists()
    assert f"Name={sample_app.name}" in content
    assert f'run-app "{sample_app.app_uuid}"' in content
    assert f"{sys.executable} -m web_app_launcher.main" in content
    assert desktop_file.name == f"{APP_NAME}-{sample_app.app_uuid}.desktop"


def test_remove_desktop_file_deletes_file(tmp_path, sample_app, monkeypatch):
    monkeypatch.setattr("web_app_launcher.utils.desktop_file_manager.shutil.which", lambda _: None)
    manager = DesktopFileManager(tmp_path)
    manager.create_desktop_file(sample_app)

    desktop_file = manager.get_desktop_file_path(sample_app.app_uuid)
    assert desktop_file.exists()

    manager.remove_desktop_file(sample_app.app_uuid)
    assert not desktop_file.exists()
