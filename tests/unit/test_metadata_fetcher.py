import struct
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from web_app_launcher.utils.metadata_fetcher import MAX_HTML_BYTES, MAX_ICON_BYTES, MetadataFetcher


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


def test_icon_candidates_are_unique_ordered_and_bounded(tmp_path):
    fetcher = MetadataFetcher(tmp_path)
    soup = BeautifulSoup(
        '<link rel="icon"><link rel="icon" href="/first.png">'
        '<link rel="icon" href="https://example.com/first.png">'
        + "".join(f'<link rel="icon" href="/{i}.png">' for i in range(20)),
        "html.parser",
    )

    assert fetcher._extract_icon_urls(soup, "https://example.com/page") == [
        "https://example.com/first.png",
        *[f"https://example.com/{i}.png" for i in range(7)],
    ]


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "ICO", "WEBP"])
def test_supported_raster_formats(tmp_path, image_format):
    source = tmp_path / "icon.download"
    with Image.new("RGB", (32, 16), "red") as image:
        image.save(source, image_format)

    result = MetadataFetcher(tmp_path)._optimize_icon(source)

    with Image.open(result) as output:
        assert output.format == "PNG"
        assert 0 < output.width <= 256
        assert 0 < output.height <= 256
    assert not source.exists()


def test_raster_output_preserves_aspect_ratio(tmp_path):
    source = tmp_path / "icon.png"
    with Image.new("RGBA", (512, 256)) as image:
        image.save(source)

    result = MetadataFetcher(tmp_path)._optimize_icon(source)

    with Image.open(result) as output:
        assert output.size == (256, 128)


@pytest.mark.parametrize("image_format", ["BMP", "GIF", "EPS"])
def test_disallowed_format_named_png(tmp_path, image_format):
    source = tmp_path / "icon.png"
    with Image.new("RGB", (16, 16)) as image:
        image.save(source, image_format)
    original = source.read_bytes()

    with pytest.raises(UnidentifiedImageError):
        MetadataFetcher(tmp_path)._optimize_icon(source)

    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("size", [(8193, 1), (1, 8193), (4001, 4000), (0, 1), (1, -1)])
def test_dimensions_rejected_before_pixel_decode(tmp_path, size):
    source = tmp_path / "icon.png"
    source.touch()
    image = MagicMock()
    image.size = size

    with patch("web_app_launcher.utils.metadata_fetcher.Image.open") as image_open:
        image_open.return_value.__enter__.return_value = image
        with pytest.raises(ValueError, match="dimensions"):
            MetadataFetcher(tmp_path)._optimize_icon(source)

    image.convert.assert_not_called()
    image.load.assert_not_called()

    assert list(tmp_path.iterdir()) == [source]


def test_only_first_animation_frame_is_used(tmp_path):
    source = tmp_path / "animated.webp"
    with Image.new("RGB", (16, 16), "red") as first, Image.new("RGB", (16, 16), "blue") as second:
        first.save(source, "WEBP", save_all=True, append_images=[second], lossless=True)

    result = MetadataFetcher(tmp_path)._optimize_icon(source)

    with Image.open(result) as output:
        assert output.getpixel((0, 0)) == (255, 0, 0, 255)
        assert output.n_frames == 1


@pytest.mark.parametrize(
    "dimensions, expected_size",
    [
        ('width="1000000000" height="500000000" viewBox="0 0 200 100"', (256, 128)),
        ('viewBox="0 0 200 100"', (256, 128)),
        ("", (256, 256)),
        ('width="0" height="0"', (256, 256)),
    ],
)
def test_svg_has_bounded_output_with_real_qt(tmp_path, dimensions, expected_size):
    source = tmp_path / "icon.svg"
    source.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" {dimensions}>'
        '<rect width="100%" height="100%" fill="red"/></svg>'
    )

    result = MetadataFetcher(tmp_path)._optimize_icon(source)

    with Image.open(result) as output:
        assert output.format == "PNG"
        assert output.size == expected_size
        assert output.getbbox() is not None


def _stub_download(body, content_type="image/png", error=None):
    def download(url, *, destination, max_bytes, **kwargs):
        assert max_bytes == (MAX_HTML_BYTES if content_type == "text/html" else MAX_ICON_BYTES)

        destination.write(body)
        if error:
            raise error

        return content_type, url

    return download


def _fail_png_save(image, output_path, *args, **kwargs):
    output_path.write_bytes(b"partial PNG")
    raise OSError("Failed to save PNG")


@pytest.mark.parametrize("failure", ["read", "decode", "save", "publish"])
def test_download_failure_cleans_files_and_preserves_existing_icon(tmp_path, failure):
    original = tmp_path / "app.png"
    with Image.new("RGB", (16, 16), "blue") as image:
        image.save(original)
    original_bytes = original.read_bytes()
    body = b"invalid" if failure == "decode" else original_bytes
    download = _stub_download(body, error=OSError() if failure == "read" else None)

    with (
        patch("web_app_launcher.utils.metadata_fetcher.fetch_public_http_response", download),
        patch.object(Image.Image, "save", new=_fail_png_save)
        if failure == "save"
        else nullcontext(),
        patch.object(Path, "replace", side_effect=OSError())
        if failure == "publish"
        else nullcontext(),
    ):
        assert (
            MetadataFetcher(tmp_path).download_icon("https://example.com/icon.png", "app") is None
        )

    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == original_bytes


def test_download_success_publishes_only_png(tmp_path):
    body = BytesIO()
    with Image.new("RGB", (16, 16), "red") as image:
        image.save(body, "JPEG")

    with patch(
        "web_app_launcher.utils.metadata_fetcher.fetch_public_http_response",
        _stub_download(body.getvalue(), "image/jpeg"),
    ):
        result = MetadataFetcher(tmp_path).download_icon("https://example.com/icon.jpg", "app")

    assert result == tmp_path / "app.png"
    assert list(tmp_path.iterdir()) == [result]

    with Image.open(result) as image:
        assert image.format == "PNG"


def test_metadata_download_and_failure_fallback(tmp_path):
    fetcher = MetadataFetcher(tmp_path)

    with patch(
        "web_app_launcher.utils.metadata_fetcher.fetch_public_http_response",
        _stub_download(b"<title>Example</title>", "text/html"),
    ):
        assert fetcher.fetch_metadata("https://example.com/page") == (
            "Example",
            "",
            ["https://example.com/favicon.ico"],
        )

    with patch(
        "web_app_launcher.utils.metadata_fetcher.fetch_public_http_response",
        _stub_download(b"partial", "text/html", ValueError("size limit")),
    ):
        assert fetcher.fetch_metadata("https://example.com/page") == ("example.com", "", [])

    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("embedded_format", ["PNG", "DIB"])
def test_ico_embedded_dimensions_checked_before_pillow_open(tmp_path, embedded_format):
    source = tmp_path / "icon.png"
    if embedded_format == "PNG":
        frame = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 8193, 1)
    else:
        frame = struct.pack("<Iii", 40, 8193, 2) + b"\x00" * 12

    source.write_bytes(
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(frame), 22)
        + frame
    )

    with patch("web_app_launcher.utils.metadata_fetcher.Image.open") as image_open:
        with pytest.raises(ValueError, match="dimensions"):
            MetadataFetcher(tmp_path)._optimize_icon(source)

    image_open.assert_not_called()

    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("failure", ["invalid", "save"])
def test_svg_failure_preserves_original_and_removes_work_files(tmp_path, failure):
    original = tmp_path / "app.png"
    original.write_bytes(b"existing icon")
    body = (
        b"invalid SVG"
        if failure == "invalid"
        else b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>'
    )

    with (
        patch(
            "web_app_launcher.utils.metadata_fetcher.fetch_public_http_response",
            _stub_download(body, "image/svg+xml"),
        ),
        patch("web_app_launcher.utils.metadata_fetcher.QImage.save", return_value=False)
        if failure == "save"
        else nullcontext(),
    ):
        assert (
            MetadataFetcher(tmp_path).download_icon("https://example.com/icon.svg", "app") is None
        )

    assert original.read_bytes() == b"existing icon"
    assert list(tmp_path.iterdir()) == [original]
