from pathlib import Path

APP_NAME = "web-app-launcher"
APP_ID = "com.nikromen.WebAppLauncher"
DEFAULT_ICON_PATH = Path(__file__).resolve().parent / "resources" / "icons" / "app-default.svg"
TRAY_SESSION_FILE = "tray_session"
TRAY_SESSION_TOKEN_BYTES = 32
TRAY_SESSION_TOKEN_HEX_LENGTH = TRAY_SESSION_TOKEN_BYTES * 2
JSON_INDENT = 4
