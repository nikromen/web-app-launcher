import os
import stat
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QStandardPaths

from web_app_launcher.constants import APP_NAME, TRAY_SESSION_FILE
from web_app_launcher.tray.tray_auth import create_session_token, read_session_token
from web_app_launcher.utils import private_files
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager
from web_app_launcher.utils.private_files import (
    atomic_write_private_text,
    ensure_private_directory,
    read_private_text,
)


@pytest.fixture(params=[0o022, 0o000])
def temporary_umask(request):
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def _resource_path(paths, resource):
    if resource == "token":
        return paths.config_dir / TRAY_SESSION_FILE
    return paths.apps_config_file if resource == "apps" else paths.profiles_config_file


def _write_resource(paths, resource):
    if resource == "token":
        create_session_token(paths.config_dir)
    elif resource == "apps":
        ConfigManager(paths).save_apps({})
    else:
        ConfigManager(paths).save_profiles({})


def _read_resource(paths, resource):
    if resource == "token":
        return read_session_token(paths.config_dir)
    if resource == "apps":
        return ConfigManager(paths).load_apps()
    return ConfigManager(paths).load_profiles()


@pytest.mark.parametrize("resource", ["apps", "profiles", "token"])
def test_sensitive_files_and_temporary_files_are_private_before_write(
    resource, path_manager, temporary_umask, monkeypatch
):
    path = _resource_path(path_manager, resource)
    original_fdopen = os.fdopen
    observed = []

    def inspect_before_write(descriptor, mode, **kwargs):
        if mode == "w":
            info = os.fstat(descriptor)
            assert stat.S_IMODE(info.st_mode) == 0o600
            assert info.st_size == 0
            assert _mode(path.parent) == 0o700
            observed.append(os.readlink(f"/proc/self/fd/{descriptor}"))
        return original_fdopen(descriptor, mode, **kwargs)

    monkeypatch.setattr(private_files.os, "fdopen", inspect_before_write)

    _write_resource(path_manager, resource)
    _write_resource(path_manager, resource)

    assert _mode(path) == 0o600
    assert len(observed) == len(set(observed)) == 2
    assert list(path.parent.iterdir()) == [path]
    assert _read_resource(path_manager, resource) is not None


@pytest.mark.parametrize("resource", ["apps", "profiles", "token"])
def test_normal_use_repairs_existing_file_permissions(resource, path_manager):
    path = _resource_path(path_manager, resource)
    _write_resource(path_manager, resource)
    path.chmod(0o666)
    content = path.read_bytes()

    _read_resource(path_manager, resource)

    assert _mode(path) == 0o600
    assert path.read_bytes() == content


@pytest.mark.parametrize("resource", ["apps", "profiles", "token"])
@pytest.mark.parametrize("failure", ["write", "replace"])
def test_failed_sensitive_write_preserves_original_and_removes_temporary_file(
    resource, failure, path_manager, monkeypatch
):
    path = _resource_path(path_manager, resource)
    _write_resource(path_manager, resource)
    original = path.read_bytes()
    original_fdopen = os.fdopen

    @contextmanager
    def failing_fdopen(descriptor, mode, **kwargs):
        with original_fdopen(descriptor, mode, **kwargs) as stream:

            def fail_write(content):
                stream.write(content[:1])
                stream.flush()
                raise OSError("Write failed")

            yield SimpleNamespace(write=fail_write)

    if failure == "write":
        monkeypatch.setattr(private_files.os, "fdopen", failing_fdopen)
    else:
        monkeypatch.setattr(
            "pathlib.Path.replace", MagicMock(side_effect=OSError("Replace failed"))
        )

    with pytest.raises(OSError):
        _write_resource(path_manager, resource)

    assert path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("resource", ["apps", "profiles", "token"])
@pytest.mark.parametrize("operation", [_read_resource, _write_resource])
def test_sensitive_files_reject_symlinks_without_touching_target(
    resource, operation, path_manager, tmp_path
):
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    outside.chmod(0o644)
    path = _resource_path(path_manager, resource)
    path.symlink_to(outside)

    with pytest.raises(OSError):
        operation(path_manager, resource)

    assert path.is_symlink()
    assert outside.read_text() == "unchanged"
    assert _mode(outside) == 0o644


@pytest.mark.parametrize("kind", ["directory", "fifo"])
@pytest.mark.parametrize("operation", [read_private_text, atomic_write_private_text])
def test_sensitive_files_reject_non_regular_file_types(kind, operation, tmp_path):
    path = tmp_path / "invalid"
    if kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)

    with pytest.raises(PermissionError):
        if operation is read_private_text:
            operation(path)
        else:
            operation(path, "secret")


def test_file_with_different_owner_is_rejected_without_chmod(tmp_path, monkeypatch):
    path = tmp_path / "config"
    path.write_text("secret")
    path.chmod(0o644)
    original_fstat = os.fstat

    def foreign_file(descriptor):
        info = original_fstat(descriptor)
        if stat.S_ISREG(info.st_mode):
            return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=info.st_mode)
        return info

    monkeypatch.setattr(private_files.os, "fstat", foreign_file)

    with pytest.raises(PermissionError, match="owned regular file"):
        read_private_text(path)

    assert _mode(path) == 0o644


def test_failure_to_repair_permissions_is_reported(tmp_path):
    path = tmp_path / "config"
    path.write_text("secret")
    path.chmod(0o644)

    with patch.object(private_files.os, "fchmod", side_effect=PermissionError("Denied")):
        with pytest.raises(PermissionError):
            read_private_text(path)

    assert path.read_text() == "secret"


@pytest.fixture
def xdg_paths(tmp_path, monkeypatch):
    locations = {}
    for location in (
        QStandardPaths.StandardLocation.ConfigLocation,
        QStandardPaths.StandardLocation.AppDataLocation,
        QStandardPaths.StandardLocation.ApplicationsLocation,
        QStandardPaths.StandardLocation.RuntimeLocation,
    ):
        parent = tmp_path / location.name
        parent.mkdir()
        parent.chmod(0o755)
        locations[location] = parent

    monkeypatch.setattr(
        QStandardPaths, "writableLocation", lambda location: str(locations[location])
    )
    return locations


def test_launcher_directories_are_private_and_xdg_parents_are_unchanged(xdg_paths, temporary_umask):
    paths = PathManager()

    for directory in (
        paths.config_dir,
        paths.data_dir,
        paths.profiles_dir,
        paths.ephemeral_profiles_dir,
    ):
        assert _mode(directory) == 0o700
    assert _mode(paths.runtime_dir) == 0o700
    assert _mode(paths.apps_dir) != 0o700
    assert all(_mode(parent) == 0o755 for parent in xdg_paths.values())


def test_existing_launcher_directories_are_repaired(xdg_paths):
    paths = PathManager()
    protected = (paths.config_dir, paths.data_dir, paths.profiles_dir, paths.ephemeral_profiles_dir)
    for directory in protected:
        directory.chmod(0o777)

    reopened = PathManager()
    assert all(
        _mode(directory) == 0o700
        for directory in (
            reopened.config_dir,
            reopened.data_dir,
            reopened.profiles_dir,
            reopened.ephemeral_profiles_dir,
        )
    )


@pytest.mark.parametrize(
    "property_name", ["config_dir", "data_dir", "profiles_dir", "ephemeral_profiles_dir"]
)
def test_launcher_directories_reject_symlinks(property_name, xdg_paths, tmp_path):
    paths = PathManager()
    directory = getattr(paths, property_name)
    directory.rmdir()
    target = tmp_path / "outside"
    target.mkdir()
    target.chmod(0o755)
    directory.symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError):
        getattr(PathManager(), property_name)

    assert _mode(target) == 0o755
    assert not list(target.iterdir())


def test_foreign_directory_is_rejected_without_chmod(tmp_path, monkeypatch):
    directory = tmp_path / APP_NAME
    directory.mkdir()
    directory.chmod(0o755)
    owner = os.geteuid()
    monkeypatch.setattr(private_files.os, "geteuid", lambda: owner + 1)

    with pytest.raises(PermissionError, match="not owned"):
        ensure_private_directory(directory)

    assert _mode(directory) == 0o755
