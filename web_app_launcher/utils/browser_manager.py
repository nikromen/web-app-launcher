import logging
import shlex
import shutil
from functools import cached_property
from typing import ClassVar, Optional

from web_app_launcher.models import Browser, BrowserProfile

logger = logging.getLogger(__name__)

FIREFOX_BROWSER_KEYS = frozenset({"firefox", "zen"})
CHROMIUM_BROWSER_KEYS = frozenset({"google-chrome", "chromium", "brave", "opera"})


def is_firefox_based(browser_key: str) -> bool:
    return browser_key in FIREFOX_BROWSER_KEYS


def is_chromium_based(browser_key: str) -> bool:
    return browser_key in CHROMIUM_BROWSER_KEYS


class BrowserManager:
    BROWSERS: ClassVar[dict[str, Browser]] = {
        "firefox": Browser(
            key="firefox",
            name="Firefox",
            executable="firefox",
            command_template=(
                "{executable} --profile {profile_path} --no-remote -foreground {incognito} {url}"
            ),
        ),
        "zen": Browser(
            key="zen",
            name="Zen Browser",
            executable="zen-browser",
            command_template=(
                "{executable} --profile {profile_path} --no-remote -foreground {incognito} {url}"
            ),
        ),
        "google-chrome": Browser(
            key="google-chrome",
            name="Google Chrome",
            executable="google-chrome-stable",
            command_template=(
                "{executable} --user-data-dir={profile_path} {app_mode} {incognito} {url}"
            ),
        ),
        "chromium": Browser(
            key="chromium",
            name="Chromium",
            executable="chromium-browser",
            command_template=(
                "{executable} --user-data-dir={profile_path} {app_mode} {incognito} {url}"
            ),
        ),
        "brave": Browser(
            key="brave",
            name="Brave",
            executable="brave-browser",
            command_template=(
                "{executable} --user-data-dir={profile_path} {app_mode} {incognito} {url}"
            ),
        ),
        "opera": Browser(
            key="opera",
            name="Opera",
            executable="opera",
            command_template=(
                "{executable} --user-data-dir={profile_path} {app_mode} {incognito} {url}"
            ),
        ),
    }

    def _detect_installed_browsers(self) -> dict[str, Browser]:
        installed = {}
        for key, browser in self.BROWSERS.items():
            if shutil.which(browser.executable):
                logger.debug("Found browser '%s': %s", key, browser.executable)
                installed[key] = browser
            else:
                logger.debug(
                    "Browser '%s' not found (executable: %s)",
                    key,
                    browser.executable,
                )

        logger.debug(
            "Browser detection complete. Found %d browser(s): %s",
            len(installed),
            list(installed.keys()),
        )
        return installed

    @cached_property
    def installed_browsers(self) -> dict[str, Browser]:
        return self._detect_installed_browsers()

    def build_launch_command(
        self,
        profile: BrowserProfile,
        url: str,
        incognito: bool,
        show_navigation_bar: bool,
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        browser = profile.browser
        params = {
            "executable": browser.executable,
            "profile_path": shlex.quote(str(profile.path)),
            "url": shlex.quote(url) if url else "",
        }
        logger.debug("Base parameters for building command: %s", params)

        if incognito:
            if is_firefox_based(browser.key):
                params["incognito"] = "--private-window"
            elif is_chromium_based(browser.key):
                params["incognito"] = "--incognito"
            else:
                logger.warning(
                    "Incognito mode requested but not supported for browser '%s'",
                    browser.key,
                )
                params["incognito"] = ""
        else:
            params["incognito"] = ""

        if is_chromium_based(browser.key):
            if not show_navigation_bar and url:
                params["app_mode"] = f"--app={shlex.quote(url)}"
                params["url"] = ""
            else:
                params["app_mode"] = ""
        else:
            params["app_mode"] = ""

        logger.debug("Final parameters after adjustments: %s", params)

        command_str = browser.command_template.format(**params).strip()
        command = shlex.split(command_str)

        if extra_args:
            command.extend(extra_args)

        logger.debug("Command built: %s", command)
        return command
