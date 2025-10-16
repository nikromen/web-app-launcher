from dataclasses import dataclass
from pathlib import Path

import pytest

from web_app_launcher.models import Browser, BrowserProfile, WebApp
from web_app_launcher.utils.browser_manager import BrowserManager


@dataclass
class FakePathManager:
    """Minimal PathManager stand-in backed by a temp directory."""

    base: Path

    def __post_init__(self) -> None:
        self.config_dir = self.base / "config"
        self.data_dir = self.base / "data"
        self.icons_dir = self.data_dir / "icons"
        self.profiles_dir = self.data_dir / "browser_profiles"
        for directory in (self.config_dir, self.data_dir, self.icons_dir, self.profiles_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def apps_config_file(self) -> Path:
        return self.config_dir / "apps.json"

    @property
    def profiles_config_file(self) -> Path:
        return self.config_dir / "profiles.json"


@pytest.fixture
def path_manager(tmp_path: Path) -> FakePathManager:
    return FakePathManager(tmp_path)


@pytest.fixture
def firefox_browser() -> Browser:
    return BrowserManager.BROWSERS["firefox"]


@pytest.fixture
def chrome_browser() -> Browser:
    return BrowserManager.BROWSERS["google-chrome"]


@pytest.fixture
def sample_profile(tmp_path: Path, firefox_browser: Browser) -> BrowserProfile:
    profile_uuid = "profile-uuid-1"
    return BrowserProfile(
        profile_uuid=profile_uuid,
        name="Test Profile",
        browser=firefox_browser,
        path=tmp_path / "profiles" / profile_uuid,
        description="Test browser profile",
    )


@pytest.fixture
def sample_app(sample_profile: BrowserProfile) -> WebApp:
    return WebApp(
        app_uuid="app-uuid-1",
        name="Test App",
        url="https://example.com",
        profile_uuid=sample_profile.profile_uuid,
        description="Test application",
    )
