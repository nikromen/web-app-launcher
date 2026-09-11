from unittest.mock import patch

from web_app_launcher.models import WebApp
from web_app_launcher.utils.tray_script_runner import build_tray_env, run_tray_command


def test_build_tray_env_sets_webapp_variables(sample_profile):
    app = WebApp(
        name="Test App",
        url="https://example.com",
        profile_uuid=sample_profile.profile_uuid,
    )

    env = build_tray_env(app, sample_profile, "show", pid=4242)

    assert env["WEBAPP_UUID"] == app.app_uuid
    assert env["WEBAPP_NAME"] == "Test App"
    assert env["WEBAPP_URL"] == "https://example.com"
    assert env["WEBAPP_PROFILE_PATH"] == str(sample_profile.path)
    assert env["WEBAPP_ACTION"] == "show"
    assert env["WEBAPP_PID"] == "4242"


@patch("web_app_launcher.utils.tray_script_runner.subprocess.Popen")
def test_run_tray_command_uses_bash_c(mock_popen, sample_profile):
    app = WebApp(
        name="Test App",
        url="https://example.com",
        profile_uuid=sample_profile.profile_uuid,
    )

    assert run_tray_command(app, sample_profile, 'echo "$WEBAPP_NAME"', "script", 1) is True

    mock_popen.assert_called_once()
    command = mock_popen.call_args.args[0]
    assert command == ["bash", "-c", 'echo "$WEBAPP_NAME"']


def test_run_tray_command_rejects_empty_command(sample_profile):
    app = WebApp(
        name="Test App",
        url="https://example.com",
        profile_uuid=sample_profile.profile_uuid,
    )

    assert run_tray_command(app, sample_profile, "   ", "show") is False
