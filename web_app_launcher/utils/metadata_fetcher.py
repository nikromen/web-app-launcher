import logging
import math
import re
import struct
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import ClassVar, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from web_app_launcher.models import WebApp
from web_app_launcher.utils.url_safety import fetch_public_http_response

logger = logging.getLogger(__name__)

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_ICON_BYTES = 5 * 1024 * 1024
MAX_ICON_CANDIDATES = 8
MAX_RASTER_SIDE = 8192
MAX_RASTER_PIXELS = 16_000_000
ICON_SIZE = 256
RASTER_FORMATS = ("PNG", "JPEG", "ICO", "WEBP")


def _validate_raster_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > MAX_RASTER_SIDE
        or height > MAX_RASTER_SIDE
        or width * height > MAX_RASTER_PIXELS
    ):
        raise ValueError("Icon dimensions exceed limits")


def _validate_ico_dimensions(icon_path: Path) -> None:
    # Pillow's ICO plugin loads pixels inside Image.open. Check embedded headers first,
    # including their actual dimensions rather than trusting the one-byte directory sizes.
    with icon_path.open("rb") as source:
        header = source.read(6)
        if not header.startswith(b"\x00\x00\x01\x00"):
            return

        count = struct.unpack_from("<H", header, 4)[0]
        entries = source.read(count * 16)
        if len(entries) != count * 16:
            raise ValueError("Truncated ICO directory")

        for index in range(count):
            offset = struct.unpack_from("<I", entries, index * 16 + 12)[0]
            source.seek(offset)
            frame_header = source.read(24)

            if frame_header.startswith(b"\x89PNG\r\n\x1a\n"):
                width, height = struct.unpack_from(">II", frame_header, 16)
            else:
                header_size = struct.unpack_from("<I", frame_header)[0]
                if header_size == 12:
                    width, height = struct.unpack_from("<HH", frame_header, 4)
                elif header_size >= 40:
                    width, height = struct.unpack_from("<ii", frame_header, 4)
                else:
                    raise ValueError("Invalid ICO bitmap header")
                height //= 2  # DIB height includes the transparency mask.

            _validate_raster_dimensions(width, height)


class MetadataFetcher:
    """Fetches metadata (title, description, icon) from URLs."""

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, icons_dir: Path) -> None:
        self.icons_dir = icons_dir

    def download_icon(self, icon_url: str, app_uuid: str) -> Optional[Path]:
        """
        Download icon from URL and save it.

        Returns:
            Path to saved icon or None if download failed
        """
        try:
            with TemporaryDirectory(dir=self.icons_dir) as temporary_dir:
                temporary_path = Path(temporary_dir)
                download_path = temporary_path / "download"

                with download_path.open("wb") as destination:
                    content_type, _final_url = fetch_public_http_response(
                        icon_url,
                        headers=self.HEADERS,
                        destination=destination,
                        max_bytes=MAX_ICON_BYTES,
                        timeout=10,
                    )

                suffix = self._guess_suffix(icon_url, content_type)
                icon_path = download_path.with_suffix(f".{suffix}")
                download_path.rename(icon_path)
                optimized = self._optimize_icon(icon_path)

                final_path = WebApp.get_icon_path(self.icons_dir, app_uuid, "png")
                optimized.replace(final_path)

                return final_path

        except Exception:
            logger.warning("Failed to download icon from %s", icon_url)
            return None

    def _guess_suffix(self, url: str, content_type: str) -> str:
        """Guess file suffix from URL or content type."""
        # try from URL
        if "." in url.split("/")[-1]:
            suffix = url.split(".")[-1].split("?")[0].lower()
            if suffix in ["png", "jpg", "jpeg", "svg", "ico", "webp"]:
                return suffix

        # try from content type
        if "png" in content_type:
            return "png"
        if "jpeg" in content_type or "jpg" in content_type:
            return "jpg"
        if "svg" in content_type:
            return "svg"
        if "icon" in content_type or "ico" in content_type:
            return "ico"

        logger.debug(
            "Could not determine icon format for URL %s, defaulting to .png",
            url,
        )
        return "png"

    def _optimize_icon(self, icon_path: Path) -> Path:
        # Keep the source intact until a complete PNG can atomically replace the target.
        with TemporaryDirectory(dir=icon_path.parent) as temporary_dir:
            output_path = Path(temporary_dir) / "optimized.png"

            if icon_path.suffix.lower() == ".svg":
                self._rasterize_svg(icon_path, output_path)
            else:
                _validate_ico_dimensions(icon_path)
                with Image.open(icon_path, formats=RASTER_FORMATS) as img:
                    _validate_raster_dimensions(*img.size)

                    # Image.open starts at the first frame; never advance animations.
                    with img.convert("RGBA") as converted:
                        converted.thumbnail((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
                        converted.save(output_path, "PNG", optimize=True)

            final_path = icon_path.with_suffix(".png")
            output_path.replace(final_path)
            if final_path != icon_path:
                icon_path.unlink()

            return final_path

    def _rasterize_svg(self, svg_path: Path, output_path: Path) -> None:
        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            raise ValueError(f"Invalid SVG icon at {svg_path}")
        renderer.setAnimationEnabled(False)

        # Use floating point viewBox dimensions: defaultSize can overflow for huge SVGs.
        size = renderer.viewBoxF().size()
        if (
            not size.isValid()
            or size.isEmpty()
            or not math.isfinite(size.width())
            or not math.isfinite(size.height())
        ):
            size.setWidth(ICON_SIZE)
            size.setHeight(ICON_SIZE)

        size.scale(ICON_SIZE, ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
        bounded_size = QSize(max(1, int(size.width())), max(1, int(size.height())))

        image = QImage(bounded_size, QImage.Format.Format_ARGB32)
        if image.isNull():
            raise ValueError("Could not allocate SVG output")

        image.fill(0)
        painter = QPainter(image)
        if not painter.isActive():
            raise ValueError("Could not paint SVG output")

        try:
            renderer.render(painter)
        finally:
            painter.end()

        if not image.save(str(output_path), "PNG"):
            raise ValueError("Could not save SVG output")

    def load_q_icon(self, icon_path: Optional[Path]) -> QIcon:
        if not icon_path or not icon_path.exists():
            return QIcon()

        return QIcon(str(icon_path))

    def fetch_metadata(self, url: str) -> tuple[str, str, list[str]]:
        """
        Fetch metadata from URL.

        Returns:
            Tuple of (title, description, icon_urls)
        """
        try:
            with TemporaryFile() as destination:
                _content_type, final_url = fetch_public_http_response(
                    url,
                    headers=self.HEADERS,
                    destination=destination,
                    max_bytes=MAX_HTML_BYTES,
                    timeout=10,
                )

                destination.seek(0)
                soup = BeautifulSoup(destination, "html.parser")

            title = self._extract_title(soup, final_url)
            description = self._extract_description(soup)
            icon_urls = self._extract_icon_urls(soup, final_url)

            return title, description, icon_urls

        except Exception:
            logger.warning("Failed to fetch metadata from %s", url)
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            return domain, "", []

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        # open graph title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return str(og_title["content"])

        # twitter title
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            return str(twitter_title["content"])

        # regular title tag
        if soup.title and soup.title.string:
            return str(soup.title.string).strip()

        # fallback to domain
        parsed = urlparse(url)
        return parsed.netloc or parsed.path

    def _extract_description(self, soup: BeautifulSoup) -> str:
        # open graph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return str(og_desc["content"])

        # twitter description
        twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
        if twitter_desc and twitter_desc.get("content"):
            return str(twitter_desc["content"])

        # meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return str(meta_desc["content"])

        return ""

    def _extract_icon_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.find_all(
            "link",
            rel=re.compile(r"apple-touch-icon|icon|shortcut icon", re.I),
        ):
            href = link.get("href")
            if not href:
                continue

            absolute = urljoin(base_url, str(href))
            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)
                if len(urls) == MAX_ICON_CANDIDATES:
                    break

        if not urls:
            parsed = urlparse(base_url)
            urls.append(f"{parsed.scheme}://{parsed.netloc}/favicon.ico")

        return urls
