import json
import logging
import tarfile
from datetime import datetime
from pathlib import Path

from web_app_launcher.models import BrowserProfile, WebApp
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration files and application config itself"""

    def __init__(self, path_manager: PathManager) -> None:
        self.paths = path_manager

    def load_apps(self) -> dict[str, WebApp]:
        if not self.paths.apps_config_file.exists():
            logger.info("Apps config file does not exist, returning empty dict")
            return {}

        with open(self.paths.apps_config_file, encoding="utf-8") as f:
            data = json.load(f)

        profiles = self.load_profiles()
        apps: dict[str, WebApp] = {}
        for app_uuid, app_data in data.items():
            app = WebApp.model_validate(app_data)
            apps[app_uuid] = app
            if app.profile_uuid not in profiles:
                logger.warning(
                    "App %s references missing profile %s",
                    app_uuid,
                    app.profile_uuid,
                )

        return apps

    def save_apps(self, apps: dict[str, WebApp]) -> None:
        data = {app_uuid: app.model_dump(mode="json") for app_uuid, app in apps.items()}
        self._write_json(self.paths.apps_config_file, data)

    def load_profiles(self) -> dict[str, BrowserProfile]:
        if not self.paths.profiles_config_file.exists():
            logger.info("Profiles config file does not exist, returning empty dict")
            return {}

        with open(self.paths.profiles_config_file, encoding="utf-8") as f:
            data = json.load(f)

        profiles: dict[str, BrowserProfile] = {}
        for profile_uuid, profile_data in data.items():
            profile = BrowserProfile.model_validate(profile_data)
            profiles[profile_uuid] = profile

        return profiles

    def save_profiles(self, profiles: dict[str, BrowserProfile]) -> None:
        data = {
            profile.profile_uuid: profile.model_dump(mode="json") for profile in profiles.values()
        }
        self._write_json(self.paths.profiles_config_file, data)

    def export_configuration(self, export_path: Path) -> None:
        with tarfile.open(export_path, "w:gz") as tarf:
            for config_file in [
                self.paths.apps_config_file,
                self.paths.profiles_config_file,
            ]:
                if config_file.exists():
                    tarf.add(config_file, config_file.name)

            for icon_file in self.paths.icons_dir.glob("*"):
                if icon_file.is_file():
                    tarf.add(icon_file, f"icons/{icon_file.name}")

    def import_configuration(self, import_path: Path, merge: bool = False) -> None:
        if not merge:
            backup_path = (
                self.paths.config_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
            )
            self.export_configuration(backup_path)

        with tarfile.open(import_path, "r:gz") as tarf:
            imported_apps = self._read_apps_from_tar(tarf)
            imported_profiles = self._read_profiles_from_tar(tarf)

            if merge:
                apps = self.load_apps()
                profiles = self.load_profiles()
                if imported_apps is not None:
                    apps.update(imported_apps)

                if imported_profiles is not None:
                    profiles.update(imported_profiles)

                self.save_apps(apps)
                self.save_profiles(profiles)
            else:
                if imported_apps is not None:
                    self.save_apps(imported_apps)

                if imported_profiles is not None:
                    self.save_profiles(imported_profiles)

            self._extract_icons_from_tar(tarf)

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        temp_path.replace(path)

    @staticmethod
    def _safe_extract_member(
        tarf: tarfile.TarFile,
        member: tarfile.TarInfo,
        destination: Path,
    ) -> None:
        destination = destination.resolve()
        target = (destination / member.name).resolve()
        if not str(target).startswith(str(destination)):
            raise ValueError(f"Unsafe path in archive: {member.name}")

        extract_kwargs: dict = {}
        if hasattr(tarfile, "data_filter"):
            extract_kwargs["filter"] = "data"

        tarf.extract(member, destination, **extract_kwargs)

    def _read_apps_from_tar(self, tarf: tarfile.TarFile) -> dict[str, WebApp] | None:
        raw = self._read_json_member(tarf, "apps.json")
        if raw is None:
            return None

        return {app_uuid: WebApp.model_validate(app_data) for app_uuid, app_data in raw.items()}

    def _read_profiles_from_tar(self, tarf: tarfile.TarFile) -> dict[str, BrowserProfile] | None:
        raw = self._read_json_member(tarf, "profiles.json")
        if raw is None:
            return None

        return {
            profile_uuid: BrowserProfile.model_validate(profile_data)
            for profile_uuid, profile_data in raw.items()
        }

    def _extract_icons_from_tar(self, tarf: tarfile.TarFile) -> None:
        for member in tarf.getmembers():
            if not member.isfile() or not member.name.startswith("icons/"):
                continue
            self._safe_extract_member(tarf, member, self.paths.data_dir)

    @staticmethod
    def _read_json_member(tarf: tarfile.TarFile, name: str) -> dict | None:
        if name not in tarf.getnames():
            return None

        file_obj = tarf.extractfile(name)
        if file_obj is None:
            return None

        content = json.load(file_obj)
        if not isinstance(content, dict):
            return None

        return content
