from unittest.mock import MagicMock

import pytest

from web_app_launcher.launcher import AppLauncher
from web_app_launcher.models import ProfileMode
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


@pytest.mark.parametrize("profile_mode", [ProfileMode.SHARED, ProfileMode.DEDICATED])
@pytest.mark.parametrize("tray_enabled", [True, False])
def test_launch_app_starts_process(
    profile_mode,
    tray_enabled,
    path_manager,
    sample_app,
    sample_profile,
    monkeypatch,
):
    sample_app.profile_mode = profile_mode
    sample_app.tray_enabled = tray_enabled
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
    tray = MagicMock()
    tray.is_running.return_value = False

    launcher = AppLauncher(
        path_manager=path_manager,
        browser_manager=browser_manager,
        config_manager=config,
        tray_manager=tray,
    )

    pid = launcher.launch_app(sample_app.app_uuid)

    assert pid == 4242
    popen.assert_called_once()
    assert popen.call_args.kwargs["start_new_session"] is True
    if tray_enabled:
        tray.register.assert_called_once_with(sample_app, sample_profile, process, 4242)
    else:
        tray.register.assert_not_called()
    command = popen.call_args.args[0]
    assert "firefox" in command
    assert "https://example.com" in command
    assert str(sample_profile.path) in command
    assert not list(path_manager.ephemeral_profiles_dir.iterdir())


@pytest.fixture
def ephemeral_launcher(path_manager, sample_app, sample_profile, monkeypatch):
    sample_profile.path.mkdir(parents=True)
    (sample_profile.path / "prefs.js").write_text("template", encoding="utf-8")
    sample_app.profile_mode = ProfileMode.EPHEMERAL
    config = ConfigManager(path_manager)
    config.save_profiles({sample_profile.profile_uuid: sample_profile})
    config.save_apps({sample_app.app_uuid: sample_app})
    browsers = BrowserManager()
    monkeypatch.setattr(browsers, "installed_browsers", {"firefox": sample_profile.browser})
    monkeypatch.setattr(
        "web_app_launcher.launcher.shutil.which", lambda _executable: "/fake/browser"
    )
    return AppLauncher(path_manager, browsers, config)


@pytest.mark.parametrize("failure", ["popen", "before_popen"])
def test_failed_ephemeral_launch_cleans_session_and_preserves_template(
    failure, ephemeral_launcher, sample_app, sample_profile, path_manager, monkeypatch
):
    popen = MagicMock(side_effect=OSError("could not spawn browser"))
    monkeypatch.setattr("web_app_launcher.launcher.subprocess.Popen", popen)
    if failure == "before_popen":
        monkeypatch.setattr(ephemeral_launcher.browser_manager, "installed_browsers", {})
    with pytest.raises((OSError, RuntimeError)):
        ephemeral_launcher.launch_app(sample_app.app_uuid)
    assert not (path_manager.ephemeral_profiles_dir / sample_app.app_uuid).exists()
    assert (sample_profile.path / "prefs.js").read_text(encoding="utf-8") == "template"
    if failure == "before_popen":
        popen.assert_not_called()


@pytest.mark.parametrize("still_running", [True, False, None])
def test_failed_watcher_start_keeps_live_profile_and_cleans_finished_profile(
    still_running, ephemeral_launcher, sample_app, path_manager, monkeypatch
):
    process = MagicMock()
    process.pid = 4242
    group_running = MagicMock(side_effect=[True, still_running])
    monkeypatch.setattr("web_app_launcher.launcher.process_group_is_running", group_running)
    monkeypatch.setattr(
        "web_app_launcher.launcher.subprocess.Popen", MagicMock(return_value=process)
    )
    monkeypatch.setattr(
        "web_app_launcher.launcher.watch_process_and_cleanup",
        MagicMock(side_effect=RuntimeError("could not start watcher")),
    )
    with pytest.raises(RuntimeError, match="could not start watcher"):
        ephemeral_launcher.launch_app(sample_app.app_uuid)
    assert bool(list(path_manager.ephemeral_profiles_dir.rglob("prefs.js"))) is (
        still_running is not False
    )
    group_running.assert_called_with(process, 4242)
