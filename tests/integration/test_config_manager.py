import json
import tarfile
from io import BytesIO

import pytest

from web_app_launcher.models import BrowserProfile, WebApp
from web_app_launcher.utils.config_manager import ConfigManager


def test_save_and_load_apps_roundtrip(path_manager, sample_app, sample_profile):
    config = ConfigManager(path_manager)
    config.save_profiles({sample_profile.profile_uuid: sample_profile})
    config.save_apps({sample_app.app_uuid: sample_app})

    loaded = config.load_apps()
    assert sample_app.app_uuid in loaded
    assert loaded[sample_app.app_uuid].name == sample_app.name
    assert loaded[sample_app.app_uuid].url == sample_app.url


def test_save_and_load_profiles_roundtrip(path_manager, sample_profile):
    config = ConfigManager(path_manager)
    config.save_profiles({sample_profile.profile_uuid: sample_profile})

    loaded = config.load_profiles()
    assert loaded[sample_profile.profile_uuid].name == sample_profile.name
    assert loaded[sample_profile.profile_uuid].browser.key == "firefox"


def test_load_apps_returns_empty_when_missing(path_manager):
    config = ConfigManager(path_manager)
    assert config.load_apps() == {}


def test_export_and_import_configuration(path_manager, sample_app, sample_profile):
    config = ConfigManager(path_manager)
    config.save_profiles({sample_profile.profile_uuid: sample_profile})
    config.save_apps({sample_app.app_uuid: sample_app})

    export_path = path_manager.base / "export.tar.gz"
    config.export_configuration(export_path)

    path_manager.apps_config_file.unlink()
    path_manager.profiles_config_file.unlink()
    config.import_configuration(export_path, merge=False)

    loaded_apps = config.load_apps()
    loaded_profiles = config.load_profiles()
    assert loaded_apps[sample_app.app_uuid].name == sample_app.name
    assert loaded_profiles[sample_profile.profile_uuid].name == sample_profile.name


def test_import_configuration_merge_keeps_existing_apps(
    path_manager,
    sample_app,
    sample_profile,
    firefox_browser,
):
    config = ConfigManager(path_manager)
    other_profile = BrowserProfile(
        profile_uuid="profile-uuid-2",
        name="Existing Profile",
        browser=firefox_browser,
        path=path_manager.profiles_dir / "profile-uuid-2",
    )
    other_app = WebApp(
        app_uuid="app-uuid-2",
        name="Existing App",
        url="https://existing.example",
        profile_uuid=other_profile.profile_uuid,
    )

    config.save_profiles(
        {
            sample_profile.profile_uuid: sample_profile,
            other_profile.profile_uuid: other_profile,
        },
    )
    config.save_apps(
        {
            sample_app.app_uuid: sample_app,
            other_app.app_uuid: other_app,
        },
    )

    export_path = path_manager.base / "partial-export.tar.gz"
    config.save_apps({sample_app.app_uuid: sample_app})
    config.save_profiles({sample_profile.profile_uuid: sample_profile})
    config.export_configuration(export_path)

    config.save_apps({other_app.app_uuid: other_app})
    config.save_profiles({other_profile.profile_uuid: other_profile})
    config.import_configuration(export_path, merge=True)

    loaded_apps = config.load_apps()
    assert sample_app.app_uuid in loaded_apps
    assert other_app.app_uuid in loaded_apps


def test_safe_extract_member_rejects_path_traversal(path_manager):
    archive_path = path_manager.base / "evil.tar"
    with tarfile.open(archive_path, "w") as tarf:
        info = tarfile.TarInfo(name="../escape.txt")
        tarf.addfile(info, fileobj=None)

    config = ConfigManager(path_manager)
    with tarfile.open(archive_path, "r") as tarf:
        member = tarf.getmembers()[0]
        with pytest.raises(ValueError, match="Unsafe path"):
            config._safe_extract_member(tarf, member, path_manager.data_dir)


def test_read_json_member_rejects_non_dict_payload(path_manager):
    archive_path = path_manager.base / "bad-json.tar"
    payload = json.dumps(["not", "a", "dict"]).encode("utf-8")

    with tarfile.open(archive_path, "w") as tarf:
        info = tarfile.TarInfo(name="apps.json")
        info.size = len(payload)
        tarf.addfile(info, fileobj=BytesIO(payload))

    config = ConfigManager(path_manager)
    with tarfile.open(archive_path, "r") as tarf:
        assert config._read_json_member(tarf, "apps.json") is None
