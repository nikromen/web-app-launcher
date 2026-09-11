import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Property, QAbstractListModel, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from web_app_launcher.constants import DEFAULT_ICON_PATH
from web_app_launcher.models import BrowserProfile, ProfileMode, WebApp

if TYPE_CHECKING:
    from web_app_launcher.tray.tray_manager import TrayManager

from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.desktop_file_manager import DesktopFileManager
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


class AppListModel(QAbstractListModel):
    UuidRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    ProfileInfoRole = Qt.UserRole + 3
    IconPathRole = Qt.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._apps: list[WebApp] = []
        self._profiles: dict[str, BrowserProfile] = {}

    def rowCount(self, parent=None):
        return len(self._apps)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._apps):
            return None

        app = self._apps[index.row()]

        if role == self.UuidRole:
            return app.app_uuid
        if role == self.NameRole:
            return app.name
        if role == self.ProfileInfoRole:
            if app.profile_mode == ProfileMode.EPHEMERAL:
                template = self._profiles.get(app.profile_uuid)
                if template is None:
                    return "Unknown session template"
                info = f"Session template: {template.name} - {template.browser.name}"
            elif app.profile_mode == ProfileMode.DEDICATED:
                profile = self._profiles.get(app.profile_uuid)
                if profile is None:
                    return "Unknown dedicated profile"
                info = f"Dedicated: {profile.name} - {profile.browser.name}"
            else:
                profile = self._profiles.get(app.profile_uuid)
                if profile is None:
                    return "Unknown profile"
                info = f"Shared: {profile.name} - {profile.browser.name}"

            if app.incognito_mode:
                info += " [Incognito]"

            return info
        if role == self.IconPathRole:
            if app.icon_path and app.icon_path.exists():
                return QUrl.fromLocalFile(str(app.icon_path))

            return QUrl.fromLocalFile(str(DEFAULT_ICON_PATH))

        return None

    def roleNames(self):
        return {
            self.UuidRole: b"appUuid",
            self.NameRole: b"appName",
            self.ProfileInfoRole: b"profileInfo",
            self.IconPathRole: b"iconPath",
        }

    def update_apps(self, apps_dict: dict[str, WebApp], profiles: dict[str, BrowserProfile]):
        self.beginResetModel()
        self._apps = sorted(apps_dict.values(), key=lambda a: a.name.lower())
        self._profiles = profiles
        self.endResetModel()

    @Slot(int, result=str)
    def get_app_uuid_by_index(self, index: int) -> str | None:
        if 0 <= index < len(self._apps):
            return self._apps[index].app_uuid
        return None


class MainController(QObject):
    showAppDialog = Signal(str)
    showProfileManager = Signal()
    showImportDialog = Signal(str)

    showInfoMessage = Signal(str, str)
    showWarningMessage = Signal(str, str)

    def __init__(
        self,
        config_manager: ConfigManager,
        launcher,
        path_manager: PathManager,
        browser_manager: BrowserManager,
        tray_manager: Optional["TrayManager"] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.config_manager = config_manager
        self.launcher = launcher
        self.path_manager = path_manager
        self.browsers = browser_manager
        self._tray_manager = tray_manager
        self._window_visible = True

        self.apps: dict[str, WebApp] = {}
        self.profiles: dict[str, BrowserProfile] = {}
        self._app_list_model = AppListModel(self)

        self.refresh_app_list()

    @Property(QObject, constant=True)
    def appListModel(self):
        return self._app_list_model

    @Slot()
    def handle_window_closing(self):
        self._window_visible = False
        self.maybe_quit()

    @Slot()
    def maybe_quit(self):
        app = QApplication.instance()
        if app is None or self._window_visible:
            return
        if self._tray_manager is None or not self._tray_manager.has_running_apps():
            app.quit()

    @Slot()
    def quit_application(self):
        if self._tray_manager is not None:
            self._tray_manager.stop_all()

        self._window_visible = False
        app = QApplication.instance()
        if app is not None:
            app.quit()

    @Slot()
    def check_browsers_on_startup(self):
        if not self.browsers.installed_browsers:
            self.showWarningMessage.emit(
                "No Browsers Found",
                "No supported browsers found. "
                "Please install Firefox, Chrome, or another supported browser.",
            )

    @Slot()
    def refresh_app_list(self):
        logger.debug("Refreshing app list...")
        self.apps = self.config_manager.load_apps()
        self.profiles = self.config_manager.load_profiles()
        self._app_list_model.update_apps(self.apps, self.profiles)

    @Slot(str)
    def filter_apps(self, search_text: str):
        if not search_text:
            self._app_list_model.update_apps(self.apps, self.profiles)
        else:
            needle = search_text.lower()
            filtered = {
                uuid: app
                for uuid, app in self.apps.items()
                if needle in app.name.lower() or needle in app.url.lower()
            }
            self._app_list_model.update_apps(filtered, self.profiles)

    @Slot()
    def add_app(self):
        logger.debug("QML requested to add app")
        self.showAppDialog.emit("")

    @Slot(str)
    def edit_app(self, app_uuid: str):
        if not app_uuid:
            logger.warning("Edit app called with no UUID")
            return
        logger.debug("QML requested to edit app: %s", app_uuid)
        self.showAppDialog.emit(app_uuid)

    @Slot(str)
    def remove_app(self, app_uuid: str):
        app = self.apps.get(app_uuid)
        if not app:
            return

        reply = QMessageBox.question(
            None,
            "Confirm Removal",
            f"Are you sure you want to remove '{app.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        logger.debug("Removing app: %s (%s)", app.name, app_uuid)
        profile = self.profiles.get(app.profile_uuid)
        if profile and profile.is_app_profile and profile.app_uuid == app_uuid:
            if profile.profile_uuid in self.profiles:
                if profile.path.exists():
                    shutil.rmtree(profile.path)

                del self.profiles[profile.profile_uuid]
                self.config_manager.save_profiles(self.profiles)

        del self.apps[app.app_uuid]
        self.config_manager.save_apps(self.apps)

        desktop_manager = DesktopFileManager(self.path_manager.apps_dir)
        desktop_manager.remove_desktop_file(app.app_uuid)

        self.refresh_app_list()

    @Slot(str)
    def launch_app(self, app_uuid: str):
        if not self.apps.get(app_uuid):
            logger.error("Cannot launch app: UUID %s not found.", app_uuid)
            return

        logger.debug("Launching app: %s", app_uuid)
        try:
            self.launcher.launch_app(app_uuid)
        except Exception as e:
            logger.error("Failed to launch app %s: %s", app_uuid, e)
            self.showWarningMessage.emit("Launch Failed", f"Could not launch application: {e}")

    @Slot()
    def open_profile_manager(self):
        logger.debug("QML requested profile manager")
        self.showProfileManager.emit()

    @Slot()
    def export_config(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"webapp-launcher_export_{timestamp}.tar.gz"
        default_path = Path.home() / default_filename

        file_path, _ = QFileDialog.getSaveFileName(
            None,
            "Export Configuration",
            str(default_path),
            "Tar Files (*.tar.gz)",
        )
        if not file_path:
            return

        try:
            self.config_manager.export_configuration(Path(file_path))
            self.showInfoMessage.emit(
                "Export Successful",
                f"Configuration exported successfully to:\n{file_path}",
            )
        except Exception as e:
            logger.error("Export failed: %s", e)
            self.showWarningMessage.emit("Export Failed", f"Could not export configuration: {e}")

    @Slot(str, bool, result=bool)
    def do_import_config(self, file_path: str, merge: bool):
        try:
            self.config_manager.import_configuration(Path(file_path), merge)
            self.refresh_app_list()
            self.showInfoMessage.emit("Import Successful", "Configuration imported successfully!")
            return True
        except Exception as e:
            logger.error("Import failed: %s", e)
            self.showWarningMessage.emit("Import Failed", f"Could not import configuration: {e}")
            return False

    @Slot()
    def trigger_import_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Import Configuration",
            str(Path.home()),
            "Tar Files (*.tar.gz)",
        )
        if not file_path:
            return

        self.showImportDialog.emit(file_path)
