from web_app_launcher.models import BrowserProfile
from web_app_launcher.utils.browser_manager import (
    BrowserManager,
    is_chromium_based,
    is_firefox_based,
)


def test_browser_family_detection():
    assert is_firefox_based("firefox") is True
    assert is_firefox_based("zen") is True
    assert is_firefox_based("google-chrome") is False
    assert is_chromium_based("google-chrome") is True
    assert is_chromium_based("firefox") is False


def test_build_launch_command_for_firefox(sample_profile: BrowserProfile):
    manager = BrowserManager()
    command = manager.build_launch_command(
        profile=sample_profile,
        url="https://example.com",
        incognito=False,
        show_navigation_bar=True,
    )

    assert command[0] == "firefox"
    assert "--profile" in command
    assert "https://example.com" in command


def test_build_launch_command_for_firefox_incognito(sample_profile: BrowserProfile):
    manager = BrowserManager()
    command = manager.build_launch_command(
        profile=sample_profile,
        url="https://example.com",
        incognito=True,
        show_navigation_bar=True,
    )

    assert "--private-window" in command


def test_build_launch_command_for_chromium_app_mode(tmp_path, chrome_browser):
    profile = BrowserProfile(
        profile_uuid="chrome-profile",
        name="Chrome Profile",
        browser=chrome_browser,
        path=tmp_path / "chrome-profile",
    )
    manager = BrowserManager()
    command = manager.build_launch_command(
        profile=profile,
        url="https://example.com",
        incognito=False,
        show_navigation_bar=False,
    )

    assert command[0] == "google-chrome-stable"
    assert any(arg.startswith("--app=") for arg in command)
    assert "https://example.com" not in command


def test_build_launch_command_appends_extra_args(sample_profile: BrowserProfile):
    manager = BrowserManager()
    command = manager.build_launch_command(
        profile=sample_profile,
        url="https://example.com",
        incognito=False,
        show_navigation_bar=True,
        extra_args=["--new-tab"],
    )

    assert command[-1] == "--new-tab"
