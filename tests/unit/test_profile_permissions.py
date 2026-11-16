import os
import stat
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from web_app_launcher.controllers.dialog_controller import DialogController
from web_app_launcher.models import BrowserProfile
from web_app_launcher.utils.profile_fork import (
    copy_profile_tree,
    create_empty_profile,
    create_ephemeral_profile,
    ensure_managed_profile_directory,
)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


@contextmanager
def _temporary_umask(mask):
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.parametrize("mask", [0o022, 0o000])
def test_empty_and_ephemeral_profiles_are_private(mask, tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    unrelated.chmod(0o755)
    profiles = tmp_path / "profiles"
    with _temporary_umask(mask):
        empty = BrowserProfile.get_profile_path(profiles, "empty")
        empty.chmod(0o777)
        create_empty_profile(empty)
        ephemeral = create_ephemeral_profile(profiles / "ephemeral", "app")

    for directory in (profiles, empty, ephemeral, ephemeral.parent, ephemeral.parent.parent):
        assert _mode(directory) == 0o700
    assert _mode(unrelated) == 0o755


@pytest.mark.parametrize("mask", [0o022, 0o000])
@pytest.mark.parametrize("with_template", [True, False])
def test_dedicated_profile_is_private_and_template_is_unchanged(
    mask, with_template, path_manager, sample_profile
):
    source = sample_profile.path
    source.mkdir(parents=True)
    source.chmod(0o755)
    preferences = source / "prefs.js"
    preferences.write_text("template")
    preferences.chmod(0o644)
    extension = source / "extension"
    extension.mkdir()
    extension.chmod(0o755)
    controller = SimpleNamespace(
        paths=path_manager,
        _all_profiles={sample_profile.profile_uuid: sample_profile},
    )

    with _temporary_umask(mask):
        profile = DialogController._create_dedicated_profile(
            controller,
            "app",
            "App",
            sample_profile.browser,
            sample_profile.profile_uuid if with_template else None,
        )

    assert _mode(profile.path) == 0o700
    assert profile.is_app_profile
    assert _mode(source) == 0o755
    assert _mode(preferences) == 0o644
    assert preferences.read_text() == "template"
    if with_template:
        assert (profile.path / "prefs.js").read_text() == "template"
        assert _mode(profile.path / "prefs.js") == 0o644
        assert _mode(profile.path / "extension") == 0o755


@pytest.mark.parametrize("mask", [0o022, 0o000])
def test_copy_into_ephemeral_profile_preserves_private_root(mask, tmp_path):
    source = tmp_path / "template"
    source.mkdir()
    source.chmod(0o755)
    (source / "prefs.js").write_text("template")

    with _temporary_umask(mask):
        destination = create_ephemeral_profile(tmp_path / "ephemeral", "app")
        copy_profile_tree(source, destination)

    assert _mode(destination) == 0o700
    assert _mode(source) == 0o755
    assert (source / "prefs.js").read_text() == "template"
    assert (destination / "prefs.js").read_text() == "template"


def test_failed_copy_leaves_profile_root_private(tmp_path, monkeypatch):
    source = tmp_path / "template"
    source.mkdir()
    destination = tmp_path / "destination"

    def fail_copy(*args, **kwargs):
        destination.chmod(0o755)
        raise OSError("Copy failed")

    monkeypatch.setattr("web_app_launcher.utils.profile_fork.shutil.copytree", fail_copy)

    with pytest.raises(OSError):
        copy_profile_tree(source, destination)

    assert _mode(destination) == 0o700


@pytest.mark.parametrize("operation", [create_empty_profile, copy_profile_tree])
def test_profile_root_symlink_is_rejected(operation, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    target.chmod(0o755)
    (target / "keep").write_text("unchanged")
    destination = tmp_path / "profile"
    destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError):
        if operation is copy_profile_tree:
            operation(tmp_path / "source", destination)
        else:
            operation(destination)

    assert destination.is_symlink()
    assert _mode(target) == 0o755
    assert (target / "keep").read_text() == "unchanged"


def test_managed_profile_parent_symlink_does_not_escape(tmp_path):
    base = tmp_path / "managed"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)
    (base / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        ensure_managed_profile_directory(base / "linked" / "profile", base)

    assert _mode(outside) == 0o755
    assert not list(outside.iterdir())


def test_managed_profile_checks_preserve_external_paths_and_parents(tmp_path):
    base = tmp_path / "managed"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)

    assert not ensure_managed_profile_directory(outside, base)
    assert not ensure_managed_profile_directory(base / ".." / "outside", base)
    assert _mode(outside) == 0o755
    assert not base.exists()


def test_parent_traversal_cannot_hide_a_managed_symlink(tmp_path):
    base = tmp_path / "managed"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Ambiguous"):
        ensure_managed_profile_directory(base / "linked" / ".." / "profile", base)

    assert not (base / "profile").exists()
    assert not list(outside.iterdir())


@pytest.mark.parametrize("identifier", ["..", "../outside", "/outside"])
def test_profile_path_cannot_change_permissions_outside_managed_root(tmp_path, identifier):
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)

    with pytest.raises(ValueError):
        BrowserProfile.get_profile_path(tmp_path / "managed", identifier)

    assert _mode(outside) == 0o755
