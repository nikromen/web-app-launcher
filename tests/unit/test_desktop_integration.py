from pathlib import Path

from web_app_launcher.constants import APP_ID

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def test_main_desktop_file_exists_and_references_app_id():
    desktop_file = DATA_DIR / f"{APP_ID}.desktop"
    content = desktop_file.read_text(encoding="utf-8")

    assert desktop_file.exists()
    assert f"Icon={APP_ID}" in content
    assert "Exec=web-app-launcher gui" in content
    assert f"StartupWMClass={APP_ID}" in content


def test_metainfo_file_exists_and_references_app_id():
    metainfo_file = DATA_DIR / f"{APP_ID}.metainfo.xml"
    content = metainfo_file.read_text(encoding="utf-8")

    assert metainfo_file.exists()
    assert f"<id>{APP_ID}</id>" in content
    assert f"{APP_ID}.desktop" in content


def test_hicolor_icon_exists():
    icon_file = DATA_DIR / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    assert icon_file.exists()
    assert icon_file.read_text(encoding="utf-8").startswith("<svg")
