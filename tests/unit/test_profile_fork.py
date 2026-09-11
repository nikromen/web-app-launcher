import time
from unittest.mock import MagicMock

import pytest

from web_app_launcher.utils.profile_fork import (
    cleanup_ephemeral_profile,
    copy_profile_tree,
    create_empty_profile,
    create_ephemeral_profile,
    validate_ephemeral_session_path,
    watch_process_and_cleanup,
)


def test_copy_profile_tree_copies_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prefs.js").write_text("prefs", encoding="utf-8")

    dest = tmp_path / "dest"
    copy_profile_tree(source, dest)

    assert dest.exists()
    assert (dest / "prefs.js").read_text(encoding="utf-8") == "prefs"


def test_create_empty_profile_creates_directory(tmp_path):
    profile_path = tmp_path / "empty-profile"
    create_empty_profile(profile_path)
    assert profile_path.is_dir()


def test_create_ephemeral_profile_uses_app_uuid(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    path = create_ephemeral_profile(ephemeral_base, "app-123")
    assert path.exists()
    assert path.parent.name == "app-123"


def test_create_ephemeral_profile_rejects_unsafe_app_uuid(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    with pytest.raises(ValueError, match="Invalid app UUID"):
        create_ephemeral_profile(ephemeral_base, "../escape")


def test_cleanup_ephemeral_profile_removes_directory(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    path = create_ephemeral_profile(ephemeral_base, "app-123")
    cleanup_ephemeral_profile(path, ephemeral_base)
    assert not path.exists()
    assert not (ephemeral_base / "app-123").exists()


def test_cleanup_ephemeral_profile_refuses_path_outside_base(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "secret.txt").write_text("keep", encoding="utf-8")

    cleanup_ephemeral_profile(outside, ephemeral_base)

    assert outside.exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep"


def test_cleanup_ephemeral_profile_refuses_base_directory(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    ephemeral_base.mkdir(parents=True)
    nested = create_ephemeral_profile(ephemeral_base, "app-123")
    (nested / "prefs.js").write_text("prefs", encoding="utf-8")

    cleanup_ephemeral_profile(ephemeral_base, ephemeral_base)

    assert ephemeral_base.exists()
    assert nested.exists()


def test_validate_ephemeral_session_path_accepts_expected_shape(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    path = create_ephemeral_profile(ephemeral_base, "app-123")
    assert validate_ephemeral_session_path(path, ephemeral_base) == path.resolve()


def test_watch_process_and_cleanup_removes_ephemeral_profile(tmp_path):
    ephemeral_base = tmp_path / "ephemeral"
    path = create_ephemeral_profile(ephemeral_base, "app-123")

    process = MagicMock()
    process.wait.return_value = None

    watch_process_and_cleanup(process, path, ephemeral_base)
    process.wait.assert_called_once()
    time.sleep(0.05)
    assert not path.exists()
