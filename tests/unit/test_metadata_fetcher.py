from pathlib import Path

from bs4 import BeautifulSoup

from web_app_launcher.utils.metadata_fetcher import MetadataFetcher


def test_guess_suffix_from_url():
    fetcher = MetadataFetcher(Path("/tmp/icons"))
    assert fetcher._guess_suffix("https://example.com/icon.png", "") == "png"
    assert fetcher._guess_suffix("https://example.com/icon.svg?size=1", "") == "svg"


def test_guess_suffix_from_content_type():
    fetcher = MetadataFetcher(Path("/tmp/icons"))
    assert fetcher._guess_suffix("https://example.com/icon", "image/jpeg") == "jpg"


def test_extract_title_prefers_open_graph():
    fetcher = MetadataFetcher(Path("/tmp/icons"))
    soup = BeautifulSoup(
        """
        <html>
          <head>
            <title>HTML Title</title>
            <meta property="og:title" content="OG Title" />
          </head>
        </html>
        """,
        "html.parser",
    )

    assert fetcher._extract_title(soup, "https://example.com") == "OG Title"


def test_extract_description_from_meta_tag():
    fetcher = MetadataFetcher(Path("/tmp/icons"))
    soup = BeautifulSoup(
        """
        <html>
          <head>
            <meta name="description" content="Example description" />
          </head>
        </html>
        """,
        "html.parser",
    )

    assert fetcher._extract_description(soup) == "Example description"


def test_extract_icon_urls_includes_favicon_fallback():
    fetcher = MetadataFetcher(Path("/tmp/icons"))
    soup = BeautifulSoup("<html><head></head></html>", "html.parser")

    urls = fetcher._extract_icon_urls(soup, "https://example.com/page")
    assert urls == ["https://example.com/favicon.ico"]
