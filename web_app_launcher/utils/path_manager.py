import os
import stat
from functools import cached_property
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from web_app_launcher.constants import APP_NAME
from web_app_launcher.utils.private_files import ensure_private_directory


class PathManager:
    """Manages application paths for configuration, data, and icons"""

    @cached_property
    def runtime_dir(self) -> Path:
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        if not location:
            raise RuntimeError("No user runtime directory is available")

        runtime_dir = Path(location) / APP_NAME
        runtime_dir.mkdir(mode=stat.S_IRWXU, exist_ok=True)
        info = runtime_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError(f"Unsafe application runtime directory: {runtime_dir}")

        runtime_dir.chmod(stat.S_IRWXU)
        return runtime_dir

    @cached_property
    def tray_socket_file(self) -> Path:
        return self.runtime_dir / "tray.sock"

    @cached_property
    def tray_lock_file(self) -> Path:
        return self.runtime_dir / "tray.lock"

    @cached_property
    def config_dir(self) -> Path:
        config_dir = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.ConfigLocation,
                ),
            )
            / APP_NAME
        )
        return ensure_private_directory(config_dir)

    @cached_property
    def data_dir(self) -> Path:
        data_dir = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation,
                ),
            )
            / APP_NAME
        )
        return ensure_private_directory(data_dir)

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
        return ensure_private_directory(profiles_dir)

    @cached_property
    def ephemeral_profiles_dir(self) -> Path:
        ephemeral_dir = self.profiles_dir / "ephemeral"
        return ensure_private_directory(ephemeral_dir)

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
