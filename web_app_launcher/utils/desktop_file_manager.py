import shutil
import sys
from pathlib import Path

from web_app_launcher.constants import APP_NAME
from web_app_launcher.models import WebApp


class DesktopFileManager:
    def __init__(self, apps_dir: Path) -> None:
        self.apps_dir = apps_dir

    @staticmethod
    def get_desktop_filename(app_uuid: str) -> str:
        return f"{APP_NAME}-{app_uuid}.desktop"

    def get_desktop_file_path(self, app_uuid: str) -> Path:
        return self.apps_dir / self.get_desktop_filename(app_uuid)

    @staticmethod
    def _build_exec_line(app_uuid: str) -> str:
        launcher = shutil.which("web-app-launcher")
        if launcher:
            return f'{launcher} run-app "{app_uuid}"'
        return f'{sys.executable} -m web_app_launcher.main run-app "{app_uuid}"'

    @staticmethod
    def _escape_desktop_value(value: str) -> str:
        return value.replace("\n", " ").replace("\r", " ").strip()

    def create_desktop_file(self, app: WebApp) -> None:
        name = self._escape_desktop_value(app.name)
        description = self._escape_desktop_value(app.description)
        icon_line = f"Icon={app.icon_path}\n" if app.icon_path else ""
        desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={name}
Comment={description}
Exec={self._build_exec_line(app.app_uuid)}
{icon_line}Terminal=false
Categories=Network;WebBrowser;WebApps;
StartupNotify=true
"""

        desktop_file = self.get_desktop_file_path(app.app_uuid)
        desktop_file.write_text(desktop_content, encoding="utf-8")
        desktop_file.chmod(0o644)

    def remove_desktop_file(self, app_uuid: str) -> None:
        desktop_file = self.get_desktop_file_path(app_uuid)
        if desktop_file.exists():
            desktop_file.unlink()
