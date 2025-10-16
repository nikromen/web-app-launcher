from functools import cached_property
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from web_app_launcher.constants import APP_NAME


class PathManager:
    """Manages application paths for configuration, data, and icons"""

    @cached_property
    def config_dir(self) -> Path:
        config_dir = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.ConfigLocation,
                ),
            )
            / APP_NAME
        ).resolve()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @cached_property
    def data_dir(self) -> Path:
        data_dir = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation,
                ),
            )
            / APP_NAME
        ).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @cached_property
    def apps_dir(self) -> Path:
        apps_dir = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.ApplicationsLocation,
                ),
            )
            / APP_NAME
        ).resolve()
        apps_dir.mkdir(parents=True, exist_ok=True)
        return apps_dir

    @cached_property
    def profiles_dir(self) -> Path:
        profiles_dir = self.data_dir / "browser_profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        return profiles_dir

    @cached_property
    def icons_dir(self) -> Path:
        icons_dir = self.data_dir / "icons"
        icons_dir.mkdir(parents=True, exist_ok=True)
        return icons_dir

    @cached_property
    def apps_config_file(self) -> Path:
        return self.config_dir / "apps.json"

    @cached_property
    def profiles_config_file(self) -> Path:
        return self.config_dir / "profiles.json"

    @cached_property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"
