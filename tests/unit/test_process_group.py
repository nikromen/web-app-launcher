from unittest.mock import MagicMock

import pytest

from web_app_launcher.utils import process_group


@pytest.mark.parametrize("state", ["R", "S", "D", "T", "Z", "X", "x"])
def test_group_check_ignores_dead_members_and_other_groups(state, tmp_path, monkeypatch):
    member = tmp_path / "10"
    member.mkdir()
    (member / "stat").write_text(f"10 (name with ) spaces) {state} 1 42 42 0\n")
    unrelated = tmp_path / "11"
    unrelated.mkdir()
    (unrelated / "stat").write_text("11 (other) R 1 99 99 0\n")
    (tmp_path / "12").mkdir()  # A process that disappears while scanning.
    (tmp_path / "self").mkdir()
    monkeypatch.setattr(process_group, "Path", lambda _path: tmp_path)
    process = MagicMock()
    process.poll.return_value = 0
    assert process_group.process_group_is_running(process, 42) is (state not in {"Z", "X", "x"})


@pytest.mark.parametrize("failure", [PermissionError("denied"), OSError("unavailable")])
def test_group_check_reports_unknown_on_proc_error(failure, monkeypatch, caplog):
    proc = MagicMock()
    proc.iterdir.side_effect = failure
    monkeypatch.setattr(process_group, "Path", lambda _path: proc)
    process = MagicMock()
    process.poll.return_value = 0
    assert process_group.process_group_is_running(process, 42) is None
    assert "preserving profile" in caplog.text


def test_group_check_reports_unknown_on_malformed_stat(tmp_path, monkeypatch, caplog):
    member = tmp_path / "10"
    member.mkdir()
    (member / "stat").write_text("invalid stat")
    monkeypatch.setattr(process_group, "Path", lambda _path: tmp_path)
    process = MagicMock()
    process.poll.return_value = 0
    assert process_group.process_group_is_running(process, 42) is None
    assert "preserving profile" in caplog.text
