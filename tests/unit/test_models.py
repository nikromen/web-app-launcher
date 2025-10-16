import pytest

from web_app_launcher.models import BrowserProfile, WebApp, normalize_url, resolve_app_profile


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
