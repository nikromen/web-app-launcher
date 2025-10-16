import logging
import re
from pathlib import Path
from typing import ClassVar, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from web_app_launcher.models import WebApp
from web_app_launcher.utils.url_safety import fetch_public_http_response

logger = logging.getLogger(__name__)


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
            response, _final_url = fetch_public_http_response(
                icon_url,
                headers=self.HEADERS,
                timeout=10,
            )

            suffix = self._guess_suffix(
                icon_url,
                response.headers.get("content-type", ""),
            )
            icon_path = WebApp.get_icon_path(self.icons_dir, app_uuid, suffix)

            with open(icon_path, "wb") as f:
                f.write(response.content)

            optimized = self._optimize_icon(icon_path)
            if optimized.suffix.lower() != ".png":
                logger.warning("Icon at %s is not displayable after optimization", icon_path)
                return None

            return optimized

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
        if icon_path.suffix.lower() == ".svg":
            return self._rasterize_svg(icon_path)

        try:
            with Image.open(icon_path) as img:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")

                max_size = 256
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                output_path = icon_path.with_suffix(".png")
                img.save(output_path, "PNG", optimize=True)

                if output_path != icon_path:
                    icon_path.unlink()

                return output_path

        except Exception:
            logger.warning("Failed to optimize icon at %s", icon_path)
            if icon_path.exists():
                icon_path.unlink(missing_ok=True)
            raise

    def _rasterize_svg(self, svg_path: Path) -> Path:
        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            raise ValueError(f"Invalid SVG icon at {svg_path}")

        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            size = QSize(256, 256)

        image = QImage(size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()

        output_path = svg_path.with_suffix(".png")
        image.save(str(output_path), "PNG")
        if output_path != svg_path:
            svg_path.unlink()
        return output_path

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
            response, final_url = fetch_public_http_response(
                url,
                headers=self.HEADERS,
                timeout=10,
            )
            soup = BeautifulSoup(response.text, "html.parser")

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

        def add_url(href: str | None) -> None:
            if not href:
                return
            absolute = urljoin(base_url, str(href))
            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)

        for link in soup.find_all(
            "link",
            rel=re.compile(r"apple-touch-icon|icon|shortcut icon", re.I),
        ):
            add_url(link.get("href"))

        if not urls:
            parsed = urlparse(base_url)
            add_url(f"{parsed.scheme}://{parsed.netloc}/favicon.ico")

        return urls
