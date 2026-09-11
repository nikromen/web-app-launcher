import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Property, QAbstractListModel, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from web_app_launcher.models import (
    EMPTY_PROFILE_TEMPLATE,
    BrowserProfile,
    ProfileMode,
    TrayScript,
    WebApp,
    normalize_url,
)
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.desktop_file_manager import DesktopFileManager
from web_app_launcher.utils.firefox_chrome import ensure_profile_chrome_for_app
from web_app_launcher.utils.metadata_fetcher import MetadataFetcher
from web_app_launcher.utils.path_manager import PathManager
from web_app_launcher.utils.profile_fork import copy_profile_tree, create_empty_profile

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
    profileModeChanged = Signal()
    profileModeDescriptionChanged = Signal()
    profileSourceEnabledChanged = Signal()
    dedicatedProfileSummaryChanged = Signal()
    incognitoModeChanged = Signal()
    showNavigationBarChanged = Signal()
    trayEnabledChanged = Signal()
    extraArgsChanged = Signal()
    showScriptCommandChanged = Signal()
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
        self._profile_mode_list_model = SimpleListModel(self)
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
        self._profile_mode = ProfileMode.DEDICATED.value
        self._incognito_mode = False
        self._show_navigation_bar = True
        self._tray_enabled = False
        self._extra_args = ""
        self._show_script_command = ""
        self._tray_scripts: list[TrayScript] = []

        self._profile: Optional[BrowserProfile] = None
        self._is_profile_edit_mode = False
        self._profile_name = ""
        self._profile_description = ""
        self._profile_browser_key = ""

        self._populate_browser_list()
        self._populate_profile_mode_list()
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
    def profileModeListModel(self):
        return self._profile_mode_list_model

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
            self.profileModeDescriptionChanged.emit()

    @Property(str, notify=profileModeChanged)
    def profileMode(self):
        return self._profile_mode

    @profileMode.setter
    def profileMode(self, value: str):
        if self._profile_mode != value:
            self._profile_mode = value
            self.profileModeChanged.emit()
            self.profileModeDescriptionChanged.emit()
            self.profileSourceEnabledChanged.emit()
            self.dedicatedProfileSummaryChanged.emit()
            self._filter_profiles()
            if self._filtered_profile_model.get_index_by_value(self._selected_profile_uuid) < 0:
                first_profile = self._filtered_profile_model.get_value_by_index(0)
                if first_profile:
                    self.selectedProfileUuid = first_profile

    @Property(str, notify=profileModeDescriptionChanged)
    def profileModeDescription(self):
        if self._profile_mode == ProfileMode.SHARED.value:
            return (
                "This app reads and writes the selected profile directly. "
                "Other apps using the same profile see the same cookies and extensions."
            )
        if self._profile_mode == ProfileMode.EPHEMERAL.value:
            return (
                "The browser runs in a temporary copy. Closing the app removes cookies "
                "and session changes from this run. Update the template profile in "
                "Profile Manager to change what the next session starts with."
            )
        if self._is_app_edit_mode and self._app and self._app.profile_mode == ProfileMode.DEDICATED:
            profile = self._all_profiles.get(self._app.profile_uuid)
            if profile:
                return (
                    f"This app uses its dedicated profile '{profile.name}'. "
                    "Switch profile mode and save again to recreate it from a different template."
                )
        if self._selected_profile_uuid == EMPTY_PROFILE_TEMPLATE:
            return "A new empty profile will be created for this app when you save."
        return (
            "A private copy of the selected profile will be created for this app when you save. "
            "Changes stay with this app only."
        )

    @Property(bool, notify=profileSourceEnabledChanged)
    def profileSourceEnabled(self):
        editing_dedicated = (
            self._is_app_edit_mode
            and self._app is not None
            and self._app.profile_mode == ProfileMode.DEDICATED
            and self._profile_mode == ProfileMode.DEDICATED.value
        )
        return not editing_dedicated

    @Property(str, notify=dedicatedProfileSummaryChanged)
    def dedicatedProfileSummary(self):
        if not self._is_app_edit_mode or not self._app:
            return ""
        if self._app.profile_mode != ProfileMode.DEDICATED:
            return ""

        profile = self._all_profiles.get(self._app.profile_uuid)
        if not profile:
            return ""

        if profile.forked_from_profile_uuid:
            template = self._all_profiles.get(profile.forked_from_profile_uuid)
            template_name = template.name if template else "unknown profile"
            return f"Dedicated profile '{profile.name}' (copied from {template_name})"

        return f"Dedicated profile '{profile.name}' (started empty)"

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

    @Property(str, notify=showScriptCommandChanged)
    def showScriptCommand(self):
        return self._show_script_command

    @showScriptCommand.setter
    def showScriptCommand(self, value: str):
        if self._show_script_command != value:
            self._show_script_command = value
            self.showScriptCommandChanged.emit()

    def _refresh_tray_script_model(self) -> None:
        items = [
            {"name": script.name, "uuid": str(index), "description": script.command}
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
            self.profileMode = self._app.profile_mode.value
            if self._app.profile_mode == ProfileMode.DEDICATED:
                self.selectedBrowserKey = app_profile.browser.key if app_profile else ""
                self.selectedProfileUuid = (
                    app_profile.forked_from_profile_uuid or EMPTY_PROFILE_TEMPLATE
                    if app_profile
                    else EMPTY_PROFILE_TEMPLATE
                )
            elif self._app.profile_mode == ProfileMode.EPHEMERAL:
                template = self._all_profiles.get(self._app.profile_uuid)
                self.selectedBrowserKey = template.browser.key if template else ""
                self.selectedProfileUuid = self._app.profile_uuid
            else:
                self.selectedBrowserKey = app_profile.browser.key if app_profile else ""
                self.selectedProfileUuid = self._app.profile_uuid
            self.trayEnabled = self._app.tray_enabled
            self.showScriptCommand = self._app.show_script or ""
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
            self.profileMode = ProfileMode.DEDICATED.value
            self.selectedProfileUuid = EMPTY_PROFILE_TEMPLATE
            self.trayEnabled = False
            self.showScriptCommand = ""
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
        self.profileModeDescriptionChanged.emit()
        self.profileSourceEnabledChanged.emit()
        self.dedicatedProfileSummaryChanged.emit()

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
        profile_mode = ProfileMode(self._profile_mode)
        app_uuid = self._app.app_uuid if self._app else str(uuid.uuid4())

        profile: Optional[BrowserProfile] = None
        profile_uuid: str

        if profile_mode == ProfileMode.DEDICATED:
            if self._app and self._app.profile_mode == ProfileMode.DEDICATED:
                profile = self._all_profiles.get(self._app.profile_uuid)
                if not profile or not profile.is_app_profile:
                    QMessageBox.warning(
                        None, "Error", "Dedicated profile for this app was not found."
                    )
                    return False
                updated_profile = profile.model_copy(
                    update={
                        "name": f"{name} (dedicated)",
                        "description": f"Dedicated profile for {name}",
                    },
                )
                self._all_profiles[profile.profile_uuid] = updated_profile
                self.config.save_profiles(self._all_profiles)
                profile = updated_profile
                profile_uuid = updated_profile.profile_uuid
            else:
                if not profile_key:
                    QMessageBox.warning(None, "Error", "Please select a profile source.")
                    return False

                browser = self.browsers.installed_browsers.get(self._selected_browser_key)
                if not browser:
                    QMessageBox.warning(None, "Error", "Please select a browser.")
                    return False

                template_uuid = None
                if profile_key != EMPTY_PROFILE_TEMPLATE:
                    template = self._all_profiles.get(profile_key)
                    if not template or template.is_app_profile:
                        QMessageBox.warning(
                            None, "Error", "Please select a valid template profile."
                        )
                        return False
                    if template.browser.key != browser.key:
                        QMessageBox.warning(
                            None,
                            "Error",
                            "The selected template profile uses a different browser.",
                        )
                        return False
                    template_uuid = profile_key

                profile = self._create_dedicated_profile(app_uuid, name, browser, template_uuid)
                self._all_profiles[profile.profile_uuid] = profile
                self.config.save_profiles(self._all_profiles)
                self.profiles_changed.emit()
                profile_uuid = profile.profile_uuid
        elif profile_mode == ProfileMode.EPHEMERAL:
            if not profile_key or profile_key == EMPTY_PROFILE_TEMPLATE:
                QMessageBox.warning(None, "Error", "Please select a session template profile.")
                return False
            profile = self._all_profiles.get(profile_key)
            if not profile or profile.is_app_profile:
                QMessageBox.warning(
                    None, "Error", "Please select a valid session template profile."
                )
                return False
            profile_uuid = profile_key
        else:
            if not profile_key or profile_key == EMPTY_PROFILE_TEMPLATE:
                QMessageBox.warning(None, "Error", "Please select a shared profile.")
                return False
            profile = self._all_profiles.get(profile_key)
            if not profile or profile.is_app_profile:
                QMessageBox.warning(None, "Error", "Please select a valid shared profile.")
                return False
            profile_uuid = profile_key

        if profile is None:
            QMessageBox.warning(None, "Error", "Could not resolve profile.")
            return False

        final_icon_path = None

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
            "profile_mode": profile_mode,
            "profile_uuid": profile_uuid,
            "icon_path": final_icon_path,
            "description": self._app_description.strip(),
            "incognito_mode": self._incognito_mode,
            "show_navigation_bar": self._show_navigation_bar,
            "tray_enabled": self._tray_enabled,
            "extra_args": [arg.strip() for arg in self._extra_args.split() if arg.strip()],
            "show_script": self._show_script_command.strip() or None,
            "tray_scripts": [
                TrayScript(name=script.name.strip(), command=script.command.strip())
                for script in self._tray_scripts
                if script.name.strip() and script.command.strip()
            ],
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
                and old_profile.is_app_profile
                and old_profile.app_uuid == self._app.app_uuid
                and (
                    profile_mode != ProfileMode.DEDICATED
                    or old_profile.profile_uuid != profile_uuid
                )
            ):
                self._delete_dedicated_profile(old_profile)
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
        if self._profile:
            profile_data["is_app_profile"] = self._profile.is_app_profile
            profile_data["app_uuid"] = self._profile.app_uuid
            profile_data["forked_from_profile_uuid"] = self._profile.forked_from_profile_uuid

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
        using_apps = self._apps_using_profile(profile_uuid, apps)
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
    def add_tray_script(self):
        self._tray_scripts.append(TrayScript(name="New Action", command=""))
        self._refresh_tray_script_model()

    @Slot(int, str, str)
    def update_tray_script_at_index(self, index: int, name: str, command: str):
        if 0 <= index < len(self._tray_scripts):
            self._tray_scripts[index] = TrayScript(
                name=name.strip() or "New Action",
                command=command.strip(),
            )

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
            if profile.is_app_profile:
                description = f"{profile.browser.name} | Dedicated app profile"
                if profile.forked_from_profile_uuid:
                    template = self._all_profiles.get(profile.forked_from_profile_uuid)
                    if template:
                        description += f" | Forked from {template.name}"
                else:
                    description += " | Started empty"
            else:
                description = (
                    f"{profile.browser.name} | {profile.description or 'Shared template profile'}"
                )

            items.append(
                {
                    "name": profile.name,
                    "uuid": profile_uuid,
                    "description": description,
                },
            )
        self._profile_list_model.update_items(sorted(items, key=lambda x: x["name"].lower()))

        self._filter_profiles()

    def _populate_browser_list(self):
        items = []
        for browser in self.browsers.installed_browsers.values():
            items.append({"name": browser.name, "uuid": browser.key})
        self._browser_list_model.update_items(items)

    def _populate_profile_mode_list(self):
        self._profile_mode_list_model.update_items(
            [
                {
                    "name": "Shared profile",
                    "uuid": ProfileMode.SHARED.value,
                    "description": "Use an existing profile directly.",
                },
                {
                    "name": "Dedicated profile",
                    "uuid": ProfileMode.DEDICATED.value,
                    "description": "Create a private profile for this app only.",
                },
                {
                    "name": "Session template",
                    "uuid": ProfileMode.EPHEMERAL.value,
                    "description": "Start from a template copy that is discarded on close.",
                },
            ],
        )

    def _create_dedicated_profile(
        self,
        app_uuid: str,
        app_name: str,
        browser,
        template_uuid: Optional[str],
    ) -> BrowserProfile:
        profile_uuid = str(uuid.uuid4())
        profile_path = self.paths.profiles_dir / profile_uuid

        if template_uuid:
            template = self._all_profiles[template_uuid]
            copy_profile_tree(template.path, profile_path)
            forked_from = template_uuid
        else:
            create_empty_profile(profile_path)
            forked_from = None

        return BrowserProfile(
            profile_uuid=profile_uuid,
            name=f"{app_name} (dedicated)",
            browser=browser,
            path=profile_path,
            description=f"Dedicated profile for {app_name}",
            is_app_profile=True,
            app_uuid=app_uuid,
            forked_from_profile_uuid=forked_from,
        )

    def _delete_dedicated_profile(self, profile: BrowserProfile) -> None:
        if not profile.is_app_profile:
            return

        if profile.path.exists():
            shutil.rmtree(profile.path)

        self._all_profiles.pop(profile.profile_uuid, None)

    def _apps_using_profile(
        self,
        profile_uuid: str,
        apps: dict[str, WebApp],
    ) -> list[str]:
        using_apps: list[str] = []
        for app in apps.values():
            if app.profile_uuid == profile_uuid:
                using_apps.append(app.name)
                continue

            if app.profile_mode == ProfileMode.DEDICATED:
                dedicated = self._all_profiles.get(app.profile_uuid)
                if dedicated and dedicated.forked_from_profile_uuid == profile_uuid:
                    using_apps.append(f"{app.name} (dedicated copy)")

        return using_apps

    def _filter_profiles(self):
        browser_key = self.selectedBrowserKey
        if not browser_key:
            self._filtered_profile_model.update_items([])
            return

        items = []
        if self._profile_mode == ProfileMode.DEDICATED.value:
            items.append({"name": "Empty profile", "uuid": EMPTY_PROFILE_TEMPLATE})

        for profile_uuid, profile in self._all_profiles.items():
            if profile.is_app_profile:
                continue
            if profile.browser.key == browser_key:
                items.append({"name": profile.name, "uuid": profile_uuid})

        self._filtered_profile_model.update_items(items)
