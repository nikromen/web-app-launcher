from web_app_launcher.utils.firefox_chrome import (
    MARKER_FILE,
    apply_profile_chrome,
    ensure_profile_chrome_for_app,
)


def test_apply_profile_chrome_creates_chromeless_files(tmp_path):
    profile_path = tmp_path / "firefox-profile"
    apply_profile_chrome(profile_path, "chromeless")

    assert (profile_path / "chrome" / "userChrome.css").exists()
    assert (profile_path / "user.js").exists()
    assert (profile_path / MARKER_FILE).read_text(encoding="utf-8") == "chromeless\n"


def test_apply_profile_chrome_restores_default_mode(tmp_path):
    profile_path = tmp_path / "firefox-profile"
    apply_profile_chrome(profile_path, "chromeless")
    apply_profile_chrome(profile_path, "default")

    assert not (profile_path / "chrome" / "userChrome.css").exists()
    assert not (profile_path / MARKER_FILE).exists()
    assert not (profile_path / "user.js").exists()


def test_apply_profile_chrome_skips_foreign_user_chrome(tmp_path):
    profile_path = tmp_path / "firefox-profile"
    chrome_css = profile_path / "chrome" / "userChrome.css"
    chrome_css.parent.mkdir(parents=True)
    chrome_css.write_text("/* user custom css */\n", encoding="utf-8")

    apply_profile_chrome(profile_path, "chromeless")

    assert chrome_css.read_text(encoding="utf-8") == "/* user custom css */\n"
    assert not (profile_path / MARKER_FILE).exists()


def test_ensure_profile_chrome_for_app_ignores_chromium(tmp_path):
    profile_path = tmp_path / "chrome-profile"
    ensure_profile_chrome_for_app(profile_path, "google-chrome", show_navigation_bar=False)

    assert not (profile_path / "chrome" / "userChrome.css").exists()


def test_ensure_profile_chrome_for_app_applies_firefox_chromeless(tmp_path):
    profile_path = tmp_path / "firefox-profile"
    ensure_profile_chrome_for_app(profile_path, "firefox", show_navigation_bar=False)

    assert (profile_path / MARKER_FILE).exists()
