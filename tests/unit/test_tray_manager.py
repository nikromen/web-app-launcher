import os
import signal
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEvent

from web_app_launcher.controllers import main_controller
from web_app_launcher.tray import tray_manager


@pytest.fixture
def manager(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    manager = tray_manager.TrayManager()
    monkeypatch.setattr(tray_manager, "QSystemTrayIcon", MagicMock())
    monkeypatch.setattr(manager, "_icon_for_app", MagicMock(return_value=None))
    monkeypatch.setattr(manager, "_build_menu", MagicMock(return_value=None))
    monkeypatch.setattr(tray_manager, "process_group_is_running", MagicMock(return_value=True))
    monkeypatch.setattr(tray_manager.os, "killpg", MagicMock())
    yield manager
    for app_uuid in list(manager._running):
        manager._unregister(app_uuid)
    manager.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def entry(manager, sample_app, sample_profile):
    process = MagicMock(pid=424242)
    manager.register(sample_app, sample_profile, process, process.pid)
    return manager._running[sample_app.app_uuid]


def test_repeated_stop_preserves_deadline_and_waits_for_confirmed_exit(manager, entry):
    manager.stop_app(entry.app.app_uuid)
    deadline = entry.stop_deadline
    manager.stop_app(entry.app.app_uuid)
    assert entry.stop_deadline is deadline
    tray_manager.os.killpg.assert_called_once_with(entry.pgid, signal.SIGTERM)
    entry.process.wait.assert_not_called()

    entry.stop_deadline = QDeadlineTimer(0)
    manager._poll_processes()
    manager.stop_app(entry.app.app_uuid)
    manager._poll_processes()
    assert tray_manager.os.killpg.call_count == 2
    tray_manager.os.killpg.assert_called_with(entry.pgid, signal.SIGKILL)
    assert manager.is_running(entry.app.app_uuid)

    tray_manager.process_group_is_running.return_value = False
    manager._poll_processes()
    assert not manager.has_running_apps()
    assert not manager._poll_timer.isActive()
    entry.tray_icon.deleteLater.assert_called_once()


@pytest.mark.parametrize("state", [True, None])
def test_registration_cannot_replace_live_or_unknown_entry(state, manager, entry):
    manager.stop_app(entry.app.app_uuid)
    tray_manager.process_group_is_running.return_value = state
    with pytest.raises(RuntimeError, match="refusing replacement"):
        manager.register(entry.app, entry.profile, MagicMock(pid=434343), 434343)
    assert manager._running[entry.app.app_uuid] is entry
    assert tray_manager.QSystemTrayIcon.call_count == 1


def test_registration_can_replace_confirmed_dead_entry(manager, entry):
    tray_manager.process_group_is_running.return_value = False
    replacement = MagicMock(pid=434343)
    manager.register(entry.app, entry.profile, replacement, replacement.pid)
    assert manager._running[entry.app.app_uuid].process is replacement


def test_unknown_state_refuses_stop_and_remains_tracked(manager, entry, caplog):
    tray_manager.process_group_is_running.return_value = None
    with pytest.raises(RuntimeError, match="state is unknown"):
        manager.stop_app(entry.app.app_uuid)
    manager._poll_processes()
    assert manager.is_running(entry.app.app_uuid)
    tray_manager.os.killpg.assert_not_called()
    assert entry.stop_deadline is None
    assert "state is unknown" in caplog.text


def test_unknown_state_defers_escalation_until_it_can_be_checked(manager, entry):
    manager.stop_app(entry.app.app_uuid)
    entry.stop_deadline = QDeadlineTimer(0)
    tray_manager.process_group_is_running.return_value = None
    manager._poll_processes()
    assert tray_manager.os.killpg.call_count == 1
    assert not entry.kill_sent
    assert manager.has_running_apps()
    tray_manager.process_group_is_running.return_value = True
    manager._poll_processes()
    assert entry.kill_sent
    assert tray_manager.os.killpg.call_count == 2


@pytest.mark.parametrize("pgid", [0, 1, -1, os.getpgrp(), 434343])
def test_stop_protects_launcher_and_unsafe_groups(pgid, manager, entry):
    entry.pgid = pgid
    with pytest.raises(RuntimeError, match="unsafe process group"):
        manager.stop_app(entry.app.app_uuid)
    tray_manager.os.killpg.assert_not_called()
    assert manager.has_running_apps()


def test_permission_error_refuses_stop_and_keeps_entry(manager, entry, caplog):
    tray_manager.os.killpg.side_effect = PermissionError("denied")
    with pytest.raises(RuntimeError, match="Cannot send SIGTERM"):
        manager.stop_app(entry.app.app_uuid)
    assert manager.has_running_apps()
    assert entry.stop_deadline is None
    assert "denied" in caplog.text


@pytest.mark.parametrize("state", [True, False, None])
def test_missing_group_is_removed_only_after_confirmation(state, manager, entry):
    tray_manager.os.killpg.side_effect = ProcessLookupError("missing")
    tray_manager.process_group_is_running.side_effect = [True, state]
    if state is False:
        manager.stop_app(entry.app.app_uuid)
        assert not manager.has_running_apps()
    else:
        with pytest.raises(RuntimeError, match="Cannot send SIGTERM"):
            manager.stop_app(entry.app.app_uuid)
        assert manager.has_running_apps()


def test_failed_escalation_is_logged_once_and_keeps_tracking(manager, entry, caplog):
    manager.stop_app(entry.app.app_uuid)
    entry.stop_deadline = QDeadlineTimer(0)
    tray_manager.os.killpg.side_effect = PermissionError("denied")
    manager._poll_processes()
    manager._poll_processes()
    manager.stop_app(entry.app.app_uuid)
    assert manager.has_running_apps()
    assert tray_manager.os.killpg.call_count == 2
    assert caplog.text.count("Cannot send SIGKILL") == 1


def test_stop_all_starts_other_groups_even_if_one_is_refused(manager, entry):
    other = entry.app.model_copy(update={"app_uuid": "other"})
    process = MagicMock(pid=434343)
    manager.register(other, entry.profile, process, process.pid)
    tray_manager.os.killpg.side_effect = [PermissionError("denied"), None]
    with pytest.raises(RuntimeError, match="Could not stop all applications"):
        manager.stop_all()
    assert manager._running[other.app_uuid].stop_deadline is not None
    assert entry.stop_deadline is None
    assert manager.running_count() == 2


def test_quit_reports_refused_stop_and_keeps_event_loop(manager, entry, monkeypatch):
    config = MagicMock()
    config.load_apps.return_value = {}
    config.load_profiles.return_value = {}
    qt = MagicMock()
    monkeypatch.setattr(main_controller, "QApplication", qt)
    controller = main_controller.MainController(
        config, MagicMock(), MagicMock(), MagicMock(), manager
    )
    warnings = []
    controller.showWarningMessage.connect(lambda *message: warnings.append(message))
    tray_manager.os.killpg.side_effect = PermissionError("denied")
    try:
        controller.quit_application()
        assert manager.has_running_apps()
        assert controller._window_visible
        qt.instance.assert_not_called()
        assert warnings and "denied" in warnings[0][1]
    finally:
        controller.deleteLater()
