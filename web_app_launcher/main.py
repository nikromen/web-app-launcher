import logging
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import click
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from web_app_launcher.constants import APP_ID, APP_NAME
from web_app_launcher.controllers.dialog_controller import DialogController
from web_app_launcher.controllers.main_controller import MainController
from web_app_launcher.tray.tray_service import LaunchRouter, TrayService, try_remote_launch
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.metadata_fetcher import MetadataFetcher
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


def _get_context_settings() -> dict[str, Any]:
    return {"help_option_names": ["-h", "--help"]}


def _app_version() -> str:
    try:
        return version("web-app-launcher")
    except PackageNotFoundError:
        # TODO: remove this later
        return "0.1.0"


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    return app


@dataclass
class Context:
    paths: PathManager
    browsers: BrowserManager
    config: ConfigManager


@click.group("web-app-launcher", context_settings=_get_context_settings())
@click.option(
    "-l",
    "--log-level",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        case_sensitive=False,
    ),
    default="WARNING",
    show_default=True,
    help="Set the logging level",
)
@click.pass_context
def entry_point(ctx: click.Context, log_level: str):
    """WebApp Launcher - Launch web applications as standalone apps"""
    logger.handlers.clear()
    log_level_value = log_level.upper()
    logging.basicConfig(level=log_level_value)

    logger.debug("Log level set to %s", log_level_value)

    _ensure_qt_app()

    path_manager = PathManager()
    ctx.obj = Context(
        paths=path_manager,
        browsers=BrowserManager(),
        config=ConfigManager(path_manager),
    )


@entry_point.command("run-app")
@click.argument("app-uuid", required=True, type=str)
@click.pass_context
def run_app(ctx: click.Context, app_uuid: str):
    """Launch application by UUID (used by .desktop files)"""
    if try_remote_launch(app_uuid, ctx.obj.paths.config_dir):
        return 0

    app = _ensure_qt_app()

    tray_service = TrayService(ctx.obj.paths, ctx.obj.browsers, ctx.obj.config)
    if not tray_service.is_host:
        if try_remote_launch(app_uuid, ctx.obj.paths.config_dir):
            return 0

        logger.error("Could not start or connect to tray service")
        return 1

    try:
        tray_service.launcher.launch_app(app_uuid)
    except Exception as exc:
        logger.error("Failed to launch app %s: %s", app_uuid, exc)
        return 1

    if not tray_service.tray_manager.has_running_apps():
        return 0

    app.setQuitOnLastWindowClosed(False)
    tray_service.tray_manager.running_count_changed.connect(
        lambda _count: app.quit() if _count == 0 else None,
    )
    return app.exec()


@entry_point.command("gui")
@click.pass_context
def gui(ctx: click.Context):
    """Start the WebApp Launcher GUI."""
    app = _ensure_qt_app()
    app.setOrganizationName("nikromen")
    app.setOrganizationDomain("nikromen.com")
    app.setApplicationVersion(_app_version())
    app.setDesktopFileName(f"{APP_ID}.desktop")

    engine = QQmlApplicationEngine()

    paths: PathManager = ctx.obj.paths
    browsers: BrowserManager = ctx.obj.browsers
    config: ConfigManager = ctx.obj.config

    tray_service = TrayService(paths, browsers, config)
    metadata_fetcher = MetadataFetcher(paths.icons_dir)

    tray_manager = tray_service.tray_manager if tray_service.is_host else None
    main_controller = MainController(
        config,
        LaunchRouter(tray_service),
        paths,
        browsers,
        tray_manager,
    )
    dialog_controller = DialogController(config, browsers, paths, metadata_fetcher)

    dialog_controller.app_saved.connect(main_controller.refresh_app_list)
    dialog_controller.profiles_changed.connect(main_controller.refresh_app_list)
    dialog_controller.profiles_changed.connect(dialog_controller.refresh_all_profiles)

    engine.rootContext().setContextProperty("mainController", main_controller)
    engine.rootContext().setContextProperty("dialogController", dialog_controller)

    qml_file = Path(__file__).parent / "qml" / "MainWindow.qml"
    if not qml_file.exists():
        return -1

    engine.load(QUrl.fromLocalFile(str(qml_file)))

    if not engine.rootObjects():
        return -1

    if tray_service.is_host:
        app.setQuitOnLastWindowClosed(False)
        tray_service.tray_manager.running_count_changed.connect(main_controller.maybe_quit)

    main_controller.check_browsers_on_startup()

    return app.exec()


if __name__ == "__main__":
    entry_point()
