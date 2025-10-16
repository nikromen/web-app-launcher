import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Property, QAbstractListModel, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from web_app_launcher.models import BrowserProfile, TrayScript, WebApp, normalize_url
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.desktop_file_manager import DesktopFileManager
from web_app_launcher.utils.firefox_chrome import ensure_profile_chrome_for_app
from web_app_launcher.utils.metadata_fetcher import MetadataFetcher
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


class SimpleListModel(QAbstractListModel):
    """Generic list model for QML ComboBox and ListView bindings."""

    NameRole = Qt.UserRole + 1
    ValueRole = Qt.UserRole + 2
    DescriptionRole = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    def rowCount(self, parent=None):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None

        item = self._items[index.row()]
        if role == self.NameRole:
            return item.get("name")
        if role == self.ValueRole:
            return item.get("uuid")
        if role == self.DescriptionRole:
            return item.get("description")
        return None

    def roleNames(self):
        return {
            self.NameRole: b"name",
            self.ValueRole: b"uuid",
            self.DescriptionRole: b"description",
        }

    def update_items(self, items: list[dict]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    @Slot(int, result=str)
    def get_value_by_index(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]["uuid"]
        return ""

    @Slot(str, result=int)
    def get_index_by_value(self, value):
        for i, item in enumerate(self._items):
            if item["uuid"] == value:
                return i
        return -1


class DialogController(QObject):
    app_saved = Signal()
    profile_saved = Signal()
    profiles_changed = Signal()
    showProfileEditDialog = Signal(str)
    showIconPicker = Signal(list)

    isAppEditModeChanged = Signal()
    appNameChanged = Signal()
    appUrlChanged = Signal()
    appDescriptionChanged = Signal()
    iconPathChanged = Signal()
    selectedBrowserKeyChanged = Signal()
    selectedProfileUuidChanged = Signal()
    incognitoModeChanged = Signal()
    showNavigationBarChanged = Signal()
    trayEnabledChanged = Signal()
    extraArgsChanged = Signal()
    showScriptPathChanged = Signal()
    trayScriptsChanged = Signal()

    isProfileEditModeChanged = Signal()
    profileNameChanged = Signal()
    profileDescriptionChanged = Signal()
    profileBrowserKeyChanged = Signal()

    def __init__(
        self,
        config_manager: ConfigManager,
        browser_manager: BrowserManager,
        path_manager: PathManager,
        metadata_fetcher: MetadataFetcher,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config_manager
        self.browsers = browser_manager
        self.paths = path_manager
        self.metadata = metadata_fetcher

        self._all_profiles: dict[str, BrowserProfile] = {}

        self._browser_list_model = SimpleListModel(self)
        self._profile_list_model = SimpleListModel(self)
        self._filtered_profile_model = SimpleListModel(self)
        self._tray_script_list_model = SimpleListModel(self)

        self._app: Optional[WebApp] = None
        self._is_app_edit_mode = False
        self._fetched_icon_path: Optional[Path] = None
        self._selected_icon_path: Optional[Path] = None
        self._icon_url = QUrl()
        self._app_name = ""
        self._app_url = ""
        self._app_description = ""
        self._selected_browser_key = ""
        self._selected_profile_uuid = ""
        self._incognito_mode = False
        self._show_navigation_bar = True
        self._tray_enabled = False
        self._extra_args = ""
        self._show_script_path = ""
        self._tray_scripts: list[TrayScript] = []

        self._profile: Optional[BrowserProfile] = None
        self._is_profile_edit_mode = False
        self._profile_name = ""
        self._profile_description = ""
        self._profile_browser_key = ""

        self._populate_browser_list()
        self.refresh_all_profiles()

    @Property(QObject, constant=True)
    def browserListModel(self):
        return self._browser_list_model

    @Property(QObject, constant=True)
    def profileListModel(self):
        return self._profile_list_model

    @Property(QObject, constant=True)
    def filteredProfileModel(self):
        return self._filtered_profile_model

    @Property(QObject, constant=True)
    def trayScriptListModel(self):
        return self._tray_script_list_model

    @Property(bool, notify=isAppEditModeChanged)
    def isAppEditMode(self):
        return self._is_app_edit_mode

    @Property(str, notify=appNameChanged)
    def appName(self):
        return self._app_name

    @appName.setter
    def appName(self, value: str):
        if self._app_name != value:
            self._app_name = value
            self.appNameChanged.emit()

    @Property(str, notify=appUrlChanged)
    def appUrl(self):
        return self._app_url

    @appUrl.setter
    def appUrl(self, value: str):
        if self._app_url != value:
            self._app_url = value
            self.appUrlChanged.emit()

    @Property(str, notify=appDescriptionChanged)
    def appDescription(self):
        return self._app_description

    @appDescription.setter
    def appDescription(self, value: str):
        if self._app_description != value:
            self._app_description = value
            self.appDescriptionChanged.emit()

    @Property(QUrl, notify=iconPathChanged)
    def iconPath(self):
        return self._icon_url

    @Property(bool, notify=iconPathChanged)
    def hasIcon(self):
        return not self._icon_url.isEmpty()

    def _refresh_icon_path(self) -> None:
        path_to_use = None
        if self._selected_icon_path and self._selected_icon_path.exists():
            path_to_use = self._selected_icon_path
        elif self._fetched_icon_path and self._fetched_icon_path.exists():
            path_to_use = self._fetched_icon_path
        elif self._app and self._app.icon_path and self._app.icon_path.exists():
            path_to_use = self._app.icon_path

        self._icon_url = QUrl.fromLocalFile(str(path_to_use)) if path_to_use else QUrl()
        self.iconPathChanged.emit()

    @Property(str, notify=selectedBrowserKeyChanged)
    def selectedBrowserKey(self):
        return self._selected_browser_key

    @selectedBrowserKey.setter
    def selectedBrowserKey(self, key: str):
        if self._selected_browser_key != key:
            self._selected_browser_key = key
            self.selectedBrowserKeyChanged.emit()
            self._filter_profiles()

    @Property(str, notify=selectedProfileUuidChanged)
    def selectedProfileUuid(self):
        return self._selected_profile_uuid

    @selectedProfileUuid.setter
    def selectedProfileUuid(self, uuid: str):
        if self._selected_profile_uuid != uuid:
            self._selected_profile_uuid = uuid
            self.selectedProfileUuidChanged.emit()

    @Property(bool, notify=incognitoModeChanged)
    def incognitoMode(self):
        return self._incognito_mode

    @incognitoMode.setter
    def incognitoMode(self, value: bool):
        if self._incognito_mode != value:
            self._incognito_mode = value
            self.incognitoModeChanged.emit()

    @Property(bool, notify=showNavigationBarChanged)
    def showNavigationBar(self):
        return self._show_navigation_bar

    @showNavigationBar.setter
    def showNavigationBar(self, value: bool):
        if self._show_navigation_bar != value:
            self._show_navigation_bar = value
            self.showNavigationBarChanged.emit()

    @Property(bool, notify=trayEnabledChanged)
    def trayEnabled(self):
        return self._tray_enabled

    @trayEnabled.setter
    def trayEnabled(self, value: bool):
        if self._tray_enabled != value:
            self._tray_enabled = value
            self.trayEnabledChanged.emit()

    @Property(str, notify=extraArgsChanged)
    def extraArgs(self):
        return self._extra_args

    @extraArgs.setter
    def extraArgs(self, value: str):
        if self._extra_args != value:
            self._extra_args = value
            self.extraArgsChanged.emit()

    @Property(str, notify=showScriptPathChanged)
    def showScriptPath(self):
        return self._show_script_path

    @showScriptPath.setter
    def showScriptPath(self, value: str):
        if self._show_script_path != value:
            self._show_script_path = value
            self.showScriptPathChanged.emit()

    def _refresh_tray_script_model(self) -> None:
        items = [
            {"name": script.name, "uuid": str(index), "description": str(script.path)}
            for index, script in enumerate(self._tray_scripts)
        ]
        self._tray_script_list_model.update_items(items)
        self.trayScriptsChanged.emit()

    @Property(bool, notify=isProfileEditModeChanged)
    def isProfileEditMode(self):
        return self._is_profile_edit_mode

    @Property(str, notify=profileNameChanged)
    def profileName(self):
        return self._profile_name

    @profileName.setter
    def profileName(self, value: str):
        if self._profile_name != value:
            self._profile_name = value
            self.profileNameChanged.emit()

    @Property(str, notify=profileDescriptionChanged)
    def profileDescription(self):
        return self._profile_description

    @profileDescription.setter
    def profileDescription(self, value: str):
        if self._profile_description != value:
            self._profile_description = value
            self.profileDescriptionChanged.emit()

    @Property(str, notify=profileBrowserKeyChanged)
    def profileBrowserKey(self):
        return self._profile_browser_key

    @profileBrowserKey.setter
    def profileBrowserKey(self, key: str):
        if self._profile_browser_key != key:
            self._profile_browser_key = key
            self.profileBrowserKeyChanged.emit()

    @Slot(str)
    def open_profile_edit_dialog(self, profile_uuid: str):
        self.prepare_profile_dialog(profile_uuid)
        self.showProfileEditDialog.emit(profile_uuid)

    @Slot(str)
    def prepare_app_dialog(self, app_uuid: str):
        self.refresh_all_profiles()
        apps = self.config.load_apps()
        self._app = apps.get(app_uuid)
        self._fetched_icon_path = None
        self._selected_icon_path = None

        if self._app:
            self._is_app_edit_mode = True
            self.appName = self._app.name
            self.appUrl = self._app.url
            self.appDescription = self._app.description
            self.incognitoMode = self._app.incognito_mode
            self.showNavigationBar = self._app.show_navigation_bar
            self.extraArgs = " ".join(self._app.extra_args) if self._app.extra_args else ""
            app_profile = self._all_profiles.get(self._app.profile_uuid)
            self.selectedBrowserKey = app_profile.browser.key if app_profile else ""
            if app_profile and app_profile.is_default_profile:
                self.selectedProfileUuid = app_profile.browser.key
            else:
                self.selectedProfileUuid = self._app.profile_uuid
            self.trayEnabled = self._app.tray_enabled
            self.showScriptPath = str(self._app.show_script) if self._app.show_script else ""
            self._tray_scripts = list(self._app.tray_scripts)
        else:
            self._is_app_edit_mode = False
            self.appName = ""
            self.appUrl = ""
            self.appDescription = ""
            self.incognitoMode = False
            self.showNavigationBar = True
            self.extraArgs = ""
            self.selectedBrowserKey = self._browser_list_model.get_value_by_index(0)
            self.selectedProfileUuid = self._filtered_profile_model.get_value_by_index(0)
            self.trayEnabled = False
            self.showScriptPath = ""
            self._tray_scripts = []

        self._refresh_tray_script_model()
        self.isAppEditModeChanged.emit()
        self.appNameChanged.emit()
        self.appUrlChanged.emit()
        self.appDescriptionChanged.emit()
        self._refresh_icon_path()
        self.incognitoModeChanged.emit()
        self.showNavigationBarChanged.emit()
        self.trayEnabledChanged.emit()
        self.extraArgsChanged.emit()
        self.selectedProfileUuidChanged.emit()

    @Slot()
    def prepare_profile_manager(self):
        self.refresh_all_profiles()

    @Slot(str)
    def prepare_profile_dialog(self, profile_uuid: str):
        self._profile = self._all_profiles.get(profile_uuid)

        if self._profile:
            self._is_profile_edit_mode = True
            self.profileName = self._profile.name
            self.profileDescription = self._profile.description
            self.profileBrowserKey = self._profile.browser.key
        else:
            self._is_profile_edit_mode = False
            self.profileName = ""
            self.profileDescription = ""
            self.profileBrowserKey = self._browser_list_model.get_value_by_index(0)

        self.isProfileEditModeChanged.emit()
        self.profileNameChanged.emit()
        self.profileDescriptionChanged.emit()
        self.profileBrowserKeyChanged.emit()

    @Slot()
    def save_app(self) -> bool:
        name = self._app_name.strip()
        url = self._app_url.strip()

        if not name:
            QMessageBox.warning(None, "Error", "Please enter an application name.")
            return False
        if not url:
            QMessageBox.warning(None, "Error", "Please enter a URL.")
            return False
        try:
            url = normalize_url(url)
            self.appUrl = url
        except ValueError as exc:
            QMessageBox.warning(None, "Error", str(exc))
            return False

        profile_key = self.selectedProfileUuid
        if not profile_key:
            QMessageBox.warning(None, "Error", "Please select a profile.")
            return False

        profile: Optional[BrowserProfile] = None
        if profile_key in self._all_profiles:
            profile = self._all_profiles[profile_key]
        else:
            browser = self.browsers.installed_browsers.get(profile_key)
            if not browser:
                QMessageBox.warning(None, "Error", f"Invalid browser key: {profile_key}")
                return False

            browser_profile_uuid = str(uuid.uuid4())
            profile = BrowserProfile(
                profile_uuid=browser_profile_uuid,
                name=f"No Profile ({browser.name})",
                browser=browser,
                path=BrowserProfile.get_profile_path(self.paths.profiles_dir, browser_profile_uuid),
                description=f"Default profile for {browser.name}",
                is_default_profile=True,
            )
            self._all_profiles[profile.profile_uuid] = profile
            self.config.save_profiles(self._all_profiles)
            self.profiles_changed.emit()

        final_icon_path = None
        app_uuid = self._app.app_uuid if self._app else str(uuid.uuid4())

        if self._selected_icon_path and self._selected_icon_path.exists():
            if self._app and self._app.icon_path and self._app.icon_path.exists():
                self._app.icon_path.unlink(missing_ok=True)

            new_icon_path = WebApp.get_icon_path(
                self.paths.icons_dir,
                app_uuid,
                self._selected_icon_path.suffix,
            )
            shutil.copy2(self._selected_icon_path, new_icon_path)
            final_icon_path = new_icon_path

        elif self._fetched_icon_path and self._fetched_icon_path.exists():
            if self._app and self._app.icon_path and self._app.icon_path.exists():
                self._app.icon_path.unlink(missing_ok=True)

            new_icon_path = WebApp.get_icon_path(
                self.paths.icons_dir,
                app_uuid,
                self._fetched_icon_path.suffix,
            )
            self._fetched_icon_path.rename(new_icon_path)
            final_icon_path = new_icon_path

        elif self._app and self._app.icon_path:
            final_icon_path = self._app.icon_path

        web_app_args = {
            "name": name,
            "url": url,
            "profile_uuid": profile.profile_uuid,
            "icon_path": final_icon_path,
            "description": self._app_description.strip(),
            "incognito_mode": self._incognito_mode,
            "show_navigation_bar": self._show_navigation_bar,
            "tray_enabled": self._tray_enabled,
            "extra_args": [arg.strip() for arg in self._extra_args.split() if arg.strip()],
            "show_script": Path(self._show_script_path) if self._show_script_path else None,
            "tray_scripts": list(self._tray_scripts),
        }

        apps = self.config.load_apps()

        if self._app is None:
            new_app = WebApp(app_uuid=app_uuid, **web_app_args)
            apps[new_app.app_uuid] = new_app
            logger.debug("Creating new app: %s", name)
        else:
            old_profile = self._all_profiles.get(self._app.profile_uuid)
            if (
                old_profile
                and old_profile.is_default_profile
                and old_profile.profile_uuid != profile.profile_uuid
            ):
                if old_profile.profile_uuid in self._all_profiles:
                    if old_profile.path.exists():
                        shutil.rmtree(old_profile.path)

                    del self._all_profiles[old_profile.profile_uuid]

                    self.config.save_profiles(self._all_profiles)
                    self.profiles_changed.emit()

            updated_app = self._app.model_copy(update=web_app_args)
            apps[updated_app.app_uuid] = updated_app
            logger.debug("Updating app: %s", name)

        self.config.save_apps(apps)

        ensure_profile_chrome_for_app(
            profile.path,
            profile.browser.key,
            self._show_navigation_bar,
        )

        desktop_manager = DesktopFileManager(self.paths.apps_dir)
        desktop_manager.create_desktop_file(apps[app_uuid])

        self.app_saved.emit()
        return True

    @Slot()
    def save_profile(self) -> bool:
        name = self._profile_name.strip()
        if not name:
            QMessageBox.warning(None, "Error", "Please enter a profile name.")
            return False

        browser_key = self._profile_browser_key
        browser = self.browsers.installed_browsers.get(browser_key)
        if not browser:
            QMessageBox.warning(None, "Error", "Invalid browser selected.")
            return False

        if self._profile:
            profile_uuid = self._profile.profile_uuid
            profile_path = self._profile.path
        else:
            profile_uuid = str(uuid.uuid4())
            profile_path = BrowserProfile.get_profile_path(self.paths.profiles_dir, profile_uuid)

        profile_data = {
            "profile_uuid": profile_uuid,
            "name": name,
            "browser": browser,
            "path": profile_path,
            "description": self._profile_description.strip(),
        }

        new_profile = BrowserProfile(**profile_data)

        self._all_profiles[new_profile.profile_uuid] = new_profile
        self.config.save_profiles(self._all_profiles)

        logger.debug("Profile saved: %s", name)
        self.profiles_changed.emit()
        self.profile_saved.emit()
        return True

    @Slot(str)
    def remove_profile(self, profile_uuid: str):
        profile = self._all_profiles.get(profile_uuid)
        if not profile:
            return

        apps = self.config.load_apps()
        using_apps = [app.name for app in apps.values() if app.profile_uuid == profile_uuid]
        if using_apps:
            QMessageBox.warning(
                None,
                "Profile In Use",
                "Cannot remove profile because it is used by:\n"
                + "\n".join(f"- {name}" for name in using_apps),
            )
            return

        reply = QMessageBox.question(
            None,
            "Confirm Removal",
            f"Are you sure you want to remove profile '{profile.name}' and all its data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        if profile.path.exists():
            shutil.rmtree(profile.path)

        del self._all_profiles[profile.profile_uuid]
        self.config.save_profiles(self._all_profiles)

        logger.debug("Profile removed: %s", profile.name)
        self.profiles_changed.emit()

    @Slot(str)
    def configure_profile(self, profile_uuid: str):
        profile = self._all_profiles.get(profile_uuid)
        if not profile:
            return

        logger.debug("Configuring profile: %s", profile.name)
        browser = self.browsers.installed_browsers.get(profile.browser.key)
        if not browser or not shutil.which(profile.browser.executable):
            QMessageBox.critical(
                None,
                "Browser Not Available",
                f"Browser '{profile.browser.name}' is not installed.",
            )
            return

        QMessageBox.information(
            None,
            "Profile Configuration",
            f"Launching {profile.browser.name} with profile '{profile.name}'.\n"
            "Install extensions and configure settings. Close the browser when done.",
        )

        ensure_profile_chrome_for_app(profile.path, profile.browser.key, True)

        command = self.browsers.build_launch_command(
            profile=profile,
            url="",
            incognito=False,
            show_navigation_bar=True,
        )
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot()
    def fetch_metadata(self):
        url = self._app_url.strip()
        if not url:
            QMessageBox.warning(None, "Error", "Please enter a URL first.")
            return
        try:
            url = normalize_url(url)
            self.appUrl = url
            title, description, icon_urls = self.metadata.fetch_metadata(url)

            if not self.appName:
                self.appName = title
            if not self.appDescription and description:
                self.appDescription = description

            if not icon_urls:
                QMessageBox.information(
                    None,
                    "Success",
                    "Metadata fetched, but no icons were found.",
                )
                return

            icon_name = self._app.app_uuid if self._app else str(uuid.uuid4())
            downloaded: list[str] = []
            for index, icon_url in enumerate(icon_urls):
                icon_path = self.metadata.download_icon(icon_url, f"{icon_name}_{index}")
                if icon_path:
                    downloaded.append(QUrl.fromLocalFile(str(icon_path)).toString())

            if not downloaded:
                QMessageBox.information(
                    None,
                    "Partial Success",
                    "Metadata fetched, but icon download failed.",
                )
                return

            if len(downloaded) == 1:
                self._set_fetched_icon(downloaded[0])
                QMessageBox.information(None, "Success", "Metadata fetched successfully.")
                return

            self.showIconPicker.emit(downloaded)

        except Exception as e:
            logger.error("Metadata fetch failed: %s", e)
            QMessageBox.warning(None, "Error", f"Failed to fetch metadata: {e}")

    @Slot(str)
    def select_fetched_icon(self, icon_path: str):
        self._set_fetched_icon(icon_path)

    def _set_fetched_icon(self, icon_path: str) -> None:
        if icon_path.startswith("file://"):
            local_path = QUrl(icon_path).toLocalFile()
        else:
            local_path = icon_path
        self._fetched_icon_path = Path(local_path)
        self._selected_icon_path = None
        self._refresh_icon_path()

    @Slot()
    def choose_show_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Choose Show Script",
            str(Path.home()),
            "Scripts (*.sh);;All Files (*)",
        )
        if file_path:
            self.showScriptPath = file_path

    @Slot()
    def clear_show_script(self):
        self.showScriptPath = ""

    @Slot()
    def add_tray_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Choose Tray Script",
            str(Path.home()),
            "Scripts (*.sh);;All Files (*)",
        )
        if not file_path:
            return

        name = Path(file_path).stem.replace("_", " ").replace("-", " ").title()
        self._tray_scripts.append(TrayScript(name=name, path=Path(file_path)))
        self._refresh_tray_script_model()

    @Slot(int)
    def remove_tray_script_at_index(self, index: int):
        if 0 <= index < len(self._tray_scripts):
            del self._tray_scripts[index]
            self._refresh_tray_script_model()

    @Slot()
    def choose_icon_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Choose Icon File",
            "",
            "Images (*.png *.jpg *.jpeg *.svg *.ico);;All Files (*)",
        )
        if file_path:
            source = Path(file_path)
            staging = WebApp.get_icon_path(
                self.paths.icons_dir,
                f"picker_{uuid.uuid4()}",
                source.suffix,
            )
            shutil.copy2(source, staging)
            icon_path = self.metadata._optimize_icon(staging)
            self._selected_icon_path = icon_path
            self._fetched_icon_path = None
            self._refresh_icon_path()

    @Slot()
    def refresh_all_profiles(self):
        logger.debug("Refreshing all profiles for dialogs")
        self._all_profiles = self.config.load_profiles()

        items = []
        for profile_uuid, profile in self._all_profiles.items():
            if profile.is_default_profile:
                continue
            items.append(
                {
                    "name": profile.name,
                    "uuid": profile_uuid,
                    "description": (
                        f"{profile.browser.name} | {profile.description or 'No description'}"
                    ),
                },
            )
        self._profile_list_model.update_items(sorted(items, key=lambda x: x["name"].lower()))

        self._filter_profiles()

    def _populate_browser_list(self):
        items = []
        for browser in self.browsers.installed_browsers.values():
            items.append({"name": browser.name, "uuid": browser.key})
        self._browser_list_model.update_items(items)

    def _filter_profiles(self):
        browser_key = self.selectedBrowserKey
        if not browser_key:
            self._filtered_profile_model.update_items([])
            return

        items = []
        browser = self.browsers.installed_browsers.get(browser_key)
        if browser:
            items.append({"name": "No Profile", "uuid": browser.key})

        for profile_uuid, profile in self._all_profiles.items():
            if profile.is_default_profile:
                continue
            if profile.browser.key == browser_key:
                items.append({"name": profile.name, "uuid": profile_uuid})

        self._filtered_profile_model.update_items(items)
