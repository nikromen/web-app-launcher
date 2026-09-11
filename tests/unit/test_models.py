import pytest

from web_app_launcher.models import (
    BrowserProfile,
    ProfileMode,
    WebApp,
    normalize_url,
    resolve_app_profile,
    resolve_launch_profile,
)


def test_normalize_url_adds_https():
    assert normalize_url("example.com") == "https://example.com"


def test_normalize_url_strips_whitespace():
    assert normalize_url("  https://example.com  ") == "https://example.com"


def test_normalize_url_rejects_empty():
    with pytest.raises(ValueError, match="URL cannot be empty"):
        normalize_url("   ")


def test_web_app_normalizes_url_on_validation():
    app = WebApp(
        name="Example",
        url="example.com",
        profile_uuid="profile-1",
    )
    assert app.url == "https://example.com"


def test_resolve_app_profile_returns_matching_profile(sample_app, sample_profile):
    profiles = {sample_profile.profile_uuid: sample_profile}
    assert resolve_app_profile(sample_app, profiles) == sample_profile


def test_resolve_app_profile_missing_raises(sample_app):
    with pytest.raises(ValueError, match="not found"):
        resolve_app_profile(sample_app, {})


def test_browser_profile_creates_profile_directory(path_manager):
    profile_path = BrowserProfile.get_profile_path(path_manager.profiles_dir, "abc-123")
    assert profile_path.exists()
    assert profile_path == path_manager.profiles_dir / "abc-123"


def test_resolve_launch_profile_shared_uses_profile_directly(sample_app, sample_profile):
    profiles = {sample_profile.profile_uuid: sample_profile}
    context = resolve_launch_profile(
        sample_app,
        profiles,
        sample_profile.path.parent / "ephemeral",
    )
    assert context.profile == sample_profile
    assert context.ephemeral_path is None


def test_resolve_launch_profile_ephemeral_creates_copy(sample_profile, tmp_path):
    sample_profile.path.mkdir(parents=True, exist_ok=True)
    (sample_profile.path / "prefs.js").write_text("prefs", encoding="utf-8")
    app = WebApp(
        name="Ephemeral App",
        url="https://example.com",
        profile_mode=ProfileMode.EPHEMERAL,
        profile_uuid=sample_profile.profile_uuid,
    )
    profiles = {sample_profile.profile_uuid: sample_profile}
    ephemeral_dir = tmp_path / "ephemeral"

    context = resolve_launch_profile(app, profiles, ephemeral_dir)

    assert context.ephemeral_path is not None
    assert context.ephemeral_path.exists()
    assert context.profile.path == context.ephemeral_path
    assert (context.ephemeral_path / "prefs.js").read_text(encoding="utf-8") == "prefs"
