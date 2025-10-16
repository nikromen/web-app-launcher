from unittest.mock import MagicMock

import pytest

from web_app_launcher.launcher import AppLauncher
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager


def test_launch_app_raises_for_missing_app(path_manager):
    launcher = AppLauncher(
        path_manager=path_manager,
        browser_manager=BrowserManager(),
        config_manager=ConfigManager(path_manager),
    )

    with pytest.raises(ValueError, match="not found"):
        launcher.launch_app("missing-app")


def test_launch_app_starts_process(
    path_manager,
    sample_app,
    sample_profile,
    monkeypatch,
):
    config = ConfigManager(path_manager)
    config.save_profiles({sample_profile.profile_uuid: sample_profile})
    config.save_apps({sample_app.app_uuid: sample_app})

    browser_manager = BrowserManager()
    monkeypatch.setattr(
        browser_manager,
        "installed_browsers",
        {"firefox": BrowserManager.BROWSERS["firefox"]},
    )
    monkeypatch.setattr(
        "web_app_launcher.launcher.shutil.which",
        lambda executable: f"/usr/bin/{executable}",
    )

    process = MagicMock()
    process.pid = 4242
    process.poll.return_value = None
    popen = MagicMock(return_value=process)
    monkeypatch.setattr("web_app_launcher.launcher.subprocess.Popen", popen)

    launcher = AppLauncher(
        path_manager=path_manager,
        browser_manager=browser_manager,
        config_manager=config,
    )

    pid = launcher.launch_app(sample_app.app_uuid)

    assert pid == 4242
    popen.assert_called_once()
    command = popen.call_args.args[0]
    assert "firefox" in command
    assert "https://example.com" in command
