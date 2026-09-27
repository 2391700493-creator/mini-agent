import re
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PositiveTokens = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]
Price = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    context_length: PositiveTokens
    max_output_tokens: PositiveTokens
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    input_price: Price | None = None
    output_price: Price | None = None
    cached_input_price: Price | None = None
    pricing_currency: str = Field(default="CNY", min_length=3, max_length=3)
    price_unit_tokens: Annotated[int, Field(strict=True, ge=1, le=1_000_000_000)] = 1_000_000

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or "?" in value
                or "#" in value
                or any(c.isspace() or ord(c) < 32 for c in value)
                or "\\" in value
            ):
                raise ValueError
            _ = url.port
        except ValueError:
            raise ValueError("请输入有效的 http(s) 服务地址，不含账号、查询参数或片段") from None
        if url.path.rstrip("/").lower().endswith("/chat/completions"):
            raise ValueError("请填写 API Base URL，移除末尾的 /chat/completions")
        return value.rstrip("/")

    @field_validator("max_output_tokens")
    @classmethod
    def validate_output(cls, value, info):
        if value > info.data.get("context_length", value):
            raise ValueError("最大输出长度不得超过上下文长度")
        return value

    @field_validator("pricing_currency")
    @classmethod
    def currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("币种须为三个大写字母，例如 CNY 或 USD。")
        return value


class ModelSave(ModelConfig):
    api_key: SecretStr | None = None

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value):
        if value is None or not value.get_secret_value().strip():
            return None
        key = value.get_secret_value().strip()
        if len(key) > 4096 or not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key):
            raise ValueError("密钥应为不含空白的 ASCII 字符，最多 4096 个字符")
        return SecretStr(key)


class ModelView(ModelConfig):
    id: str
    key_configured: bool
    is_default: bool
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class DeleteModel(BaseModel):
    replacement_id: str | None = None


class ConnectionResult(BaseModel):
    success: bool
    code: str
    message: str
    suggestion: str = ""
    reply: str | None = None
