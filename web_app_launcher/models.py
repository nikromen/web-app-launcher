import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from web_app_launcher.utils.profile_fork import (
    cleanup_ephemeral_profile,
    copy_profile_tree,
    create_ephemeral_profile,
)

EMPTY_PROFILE_TEMPLATE = "__empty__"


class ProfileMode(str, Enum):
    SHARED = "shared"
    DEDICATED = "dedicated"
    EPHEMERAL = "ephemeral"


class WebAppLauncherBaseModel(BaseModel):
    """Base model with common configurations for WebAppLauncher models."""

    model_config = ConfigDict(frozen=False)


class Browser(WebAppLauncherBaseModel):
    key: str = Field(..., min_length=1, description="Unique identifier for the browser")
    name: str = Field(..., min_length=1, description="Human-readable browser name")
    executable: str = Field(..., min_length=1, description="Executable command name")
    command_template: str = Field(
        ...,
        min_length=1,
        description="Command template for launching",
    )


class TrayScript(WebAppLauncherBaseModel):
    name: str = Field(..., min_length=1, description="Display name in tray menu")
    command: str = Field(default="", description="Shell command run via bash -c")


class BrowserProfile(WebAppLauncherBaseModel):
    profile_uuid: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique profile identifier",
    )
    name: str = Field(..., min_length=1, description="Profile name")
    browser: Browser = Field(..., description="Browser instance")
    path: Path = Field(..., description="Path to profile directory")
    description: str = Field(default="", description="Profile description")
    is_app_profile: bool = Field(
        default=False,
        description="Dedicated profile owned by a single application",
    )
    app_uuid: Optional[str] = Field(
        default=None,
        description="Application that owns this dedicated profile",
    )
    forked_from_profile_uuid: Optional[str] = Field(
        default=None,
        description="Template profile this dedicated profile was copied from",
    )
    # TODO: add user-agent support? is that needed? user can set it

    @staticmethod
    def get_profile_path(base_path: Path, profile_uuid: str) -> Path:
        path = base_path / profile_uuid
        path.mkdir(parents=True, exist_ok=True)
        return path


class WebApp(WebAppLauncherBaseModel):
    app_uuid: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique application identifier",
    )
    name: str = Field(..., min_length=1, description="Application name")
    url: str = Field(..., min_length=1, description="Application URL")
    profile_mode: ProfileMode = Field(
        default=ProfileMode.SHARED,
        description="How this application uses its browser profile",
    )
    profile_uuid: str = Field(..., min_length=1, description="Profile UUID from profiles.json")
    icon_path: Optional[Path] = Field(
        default=None,
        description="Path to application icon",
    )
    description: str = Field(default="", description="Application description")
    incognito_mode: bool = Field(
        default=False,
        description="Use private/incognito mode",
    )
    show_navigation_bar: bool = Field(
        default=True,
        description="Show browser navigation",
    )
    tray_enabled: bool = Field(
        default=False,
        description="Show a system tray icon while this application is running",
    )
    show_script: Optional[str] = Field(
        default=None,
        description="Optional shell command to show/focus the app window (WEBAPP_ACTION=show)",
    )
    tray_scripts: list[TrayScript] = Field(
        default_factory=list,
        description="Custom shell commands shown in the tray menu while the app is running",
    )
    extra_args: list[str] = Field(
        default_factory=list,
        description="Extra command line arguments for browser",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return normalize_url(v)

    @classmethod
    def get_icon_path(cls, icons_dir: Path, app_uuid: str, suffix: str) -> Path:
        return icons_dir / f"{app_uuid}.{suffix.lstrip('.')}"


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


@dataclass(frozen=True)
class LaunchProfileContext:
    profile: BrowserProfile
    ephemeral_path: Path | None = None


def resolve_app_profile(
    app: WebApp,
    profiles: dict[str, BrowserProfile],
) -> BrowserProfile:
    profile = profiles.get(app.profile_uuid)
    if profile is None:
        raise ValueError(
            f"Profile '{app.profile_uuid}' not found for application '{app.name}'",
        )
    return profile


def resolve_launch_profile(
    app: WebApp,
    profiles: dict[str, BrowserProfile],
    ephemeral_base_dir: Path,
) -> LaunchProfileContext:
    if app.profile_mode in (ProfileMode.SHARED, ProfileMode.DEDICATED):
        return LaunchProfileContext(profile=resolve_app_profile(app, profiles))

    template = resolve_app_profile(app, profiles)
    ephemeral_path = create_ephemeral_profile(ephemeral_base_dir, app.app_uuid)
    try:
        copy_profile_tree(template.path, ephemeral_path)
    except Exception:
        cleanup_ephemeral_profile(ephemeral_path, ephemeral_base_dir)
        raise

    launch_profile = template.model_copy(update={"path": ephemeral_path})
    return LaunchProfileContext(profile=launch_profile, ephemeral_path=ephemeral_path)
