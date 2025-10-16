import logging
import re
from pathlib import Path

from web_app_launcher.utils.browser_manager import is_firefox_based

logger = logging.getLogger(__name__)

MARKER_FILE = ".webapp-launcher-chrome"
MANAGED_CSS_HEADER = "/* web-app-launcher:"
USER_JS_START = "// web-app-launcher:start"
USER_JS_END = "// web-app-launcher:end"
_USER_JS_BLOCK_RE = re.compile(
    rf"{re.escape(USER_JS_START)}.*?{re.escape(USER_JS_END)}\n?",
    re.DOTALL,
)
_CHROMELESS_USER_JS_BLOCK = f"""{USER_JS_START}
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.tabs.closeWindowWithLastTab", true);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);
user_pref("browser.link.open_newwindow", 2);
user_pref("browser.link.open_newwindow.restriction", 0);
{USER_JS_END}
"""
_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources" / "firefox"


def ensure_profile_chrome_for_app(
    profile_path: Path,
    browser_key: str,
    show_navigation_bar: bool,
) -> None:
    if not is_firefox_based(browser_key):
        return

    if show_navigation_bar:
        apply_profile_chrome(profile_path, "default")
    else:
        apply_profile_chrome(profile_path, "chromeless")


def apply_profile_chrome(profile_path: Path, mode: str) -> None:
    profile_path.mkdir(parents=True, exist_ok=True)
    chrome_css = profile_path / "chrome" / "userChrome.css"
    marker_path = profile_path / MARKER_FILE

    if mode == "chromeless":
        if _is_foreign_user_chrome(chrome_css, marker_path):
            logger.warning(
                "Skipping chromeless setup for %s: custom userChrome.css detected",
                profile_path,
            )
            return

        chrome_css.parent.mkdir(parents=True, exist_ok=True)
        chrome_css.write_text(_load_chromeless_css(), encoding="utf-8")
        _upsert_user_js_block(profile_path, _CHROMELESS_USER_JS_BLOCK)
        marker_path.write_text("chromeless\n", encoding="utf-8")
        logger.debug("Applied chromeless Firefox profile chrome: %s", profile_path)
        return

    if mode == "default":
        if marker_path.exists() or _is_managed_user_chrome(chrome_css):
            if chrome_css.exists():
                chrome_css.unlink()
            chrome_dir = chrome_css.parent
            if chrome_dir.exists() and not any(chrome_dir.iterdir()):
                chrome_dir.rmdir()
            _upsert_user_js_block(profile_path, None)
            if marker_path.exists():
                marker_path.unlink()
            logger.debug("Restored default Firefox profile chrome: %s", profile_path)
        return

    raise ValueError(f"Unknown Firefox chrome mode: {mode}")


def _load_chromeless_css() -> str:
    template_path = _RESOURCES_DIR / "userChrome.chromeless.css"
    return template_path.read_text(encoding="utf-8")


def _is_managed_user_chrome(chrome_css: Path) -> bool:
    if not chrome_css.exists():
        return False
    return MANAGED_CSS_HEADER in chrome_css.read_text(encoding="utf-8")


def _is_foreign_user_chrome(chrome_css: Path, marker_path: Path) -> bool:
    if marker_path.exists():
        return False
    if not chrome_css.exists():
        return False
    content = chrome_css.read_text(encoding="utf-8").strip()
    if not content:
        return False
    return not _is_managed_user_chrome(chrome_css)


def _upsert_user_js_block(profile_path: Path, block: str | None) -> None:
    user_js = profile_path / "user.js"
    content = user_js.read_text(encoding="utf-8") if user_js.exists() else ""
    content = _USER_JS_BLOCK_RE.sub("", content).rstrip()

    if block:
        if content:
            content = f"{content}\n{block}\n"
        else:
            content = f"{block}\n"

    if content.strip():
        user_js.write_text(content, encoding="utf-8")
    elif user_js.exists():
        user_js.unlink()
