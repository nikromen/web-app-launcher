import json
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

_MessageT = TypeVar("_MessageT", bound="_TrayMessage")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


class _TrayMessage(BaseModel):
    def to_frame(self) -> bytes:
        json_data: str = self.model_dump_json(exclude_none=True)
        return json_data.encode("utf-8") + b"\n"

    @classmethod
    def from_frame(cls: type[_MessageT], frame: bytes) -> _MessageT:
        payload = json.loads(frame.decode("utf-8"), parse_constant=_reject_json_constant)
        message: _MessageT = cls.model_validate(payload)
        return message


class TrayCommand(str, Enum):
    LAUNCH = "launch"
    SHOW = "show"
    STOP = "stop"
    PING = "ping"


class TrayRequest(_TrayMessage):
    model_config = ConfigDict(strict=True)

    cmd: TrayCommand = Field(strict=False)
    token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$", repr=False)
    uuid: str = Field(default="", validate_default=True)

    @field_validator("uuid")
    @classmethod
    def validate_uuid(cls, value: str, info: ValidationInfo) -> str:
        if info.data.get("cmd") != TrayCommand.PING and not value.strip():
            raise ValueError("Application UUID is required")
        return value


class TrayResponse(_TrayMessage):
    model_config = ConfigDict(strict=True, extra="forbid")

    ok: bool
    error: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "TrayResponse":
        if self.ok and "error" in self.model_fields_set:
            raise ValueError("A successful response cannot contain an error")

        if not self.ok and (self.error is None or not self.error.strip()):
            raise ValueError("A failed response must contain an error")

        return self
