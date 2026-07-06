from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.core import AccessTokenType, HttpMethod
from lark_oapi.core.model import BaseRequest, BaseResponse

from lark_agent.config import AppConfig, load_config

BOT_INFO_URI = "/open-apis/bot/v3/info"


class LarkBotInfoError(RuntimeError):
    pass


class LarkClientLike(Protocol):
    def request(self, request: BaseRequest) -> BaseResponse: ...


@dataclass(frozen=True)
class LarkBotInfo:
    activate_status: int | None
    app_name: str
    avatar_url: str
    ip_white_list: tuple[str, ...]
    open_id: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> LarkBotInfo:
        bot = payload.get("bot")
        if not isinstance(bot, dict):
            raise LarkBotInfoError("bot info response does not contain a bot object")

        open_id = bot.get("open_id")
        if not isinstance(open_id, str) or not open_id:
            raise LarkBotInfoError("bot info response does not contain bot.open_id")

        ip_white_list = bot.get("ip_white_list")
        if not isinstance(ip_white_list, list):
            ip_white_list = []

        activate_status = bot.get("activate_status")
        return cls(
            activate_status=activate_status if isinstance(activate_status, int) else None,
            app_name=bot.get("app_name") if isinstance(bot.get("app_name"), str) else "",
            avatar_url=bot.get("avatar_url") if isinstance(bot.get("avatar_url"), str) else "",
            ip_white_list=tuple(item for item in ip_white_list if isinstance(item, str)),
            open_id=open_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "activate_status": self.activate_status,
            "app_name": self.app_name,
            "avatar_url": self.avatar_url,
            "ip_white_list": list(self.ip_white_list),
            "open_id": self.open_id,
        }


def validate_lark_app_credentials(config: AppConfig) -> None:
    missing = [
        name
        for name, value in (
            ("lark.app_id", config.lark.app_id),
            ("lark.app_secret", config.lark.app_secret),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required config values: {', '.join(missing)}")


def build_bot_info_request() -> BaseRequest:
    return (
        BaseRequest.builder()
        .http_method(HttpMethod.GET)
        .uri(BOT_INFO_URI)
        .token_types({AccessTokenType.TENANT})
        .build()
    )


def fetch_lark_bot_info(client: LarkClientLike) -> LarkBotInfo:
    response = client.request(build_bot_info_request())
    payload = _decode_response_payload(response)
    code = payload.get("code")
    if code != 0:
        message = payload.get("msg")
        raise LarkBotInfoError(f"bot info request failed: code={code!r}, msg={message!r}")
    return LarkBotInfo.from_payload(payload)


def build_lark_client(config: AppConfig) -> lark.Client:
    validate_lark_app_credentials(config)
    return (
        lark.Client.builder().app_id(config.lark.app_id).app_secret(config.lark.app_secret).build()
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Lark bot info and print the bot open_id.")
    parser.add_argument("--json", action="store_true", help="Print the bot info as JSON.")
    args = parser.parse_args(argv)

    try:
        load_dotenv(override=False)
        config = load_config()
        bot_info = fetch_lark_bot_info(build_lark_client(config))
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")

    if args.json:
        print(json.dumps(bot_info.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"app_name: {bot_info.app_name}")
        print(f"activate_status: {bot_info.activate_status}")
        print(f"open_id: {bot_info.open_id}")
    return 0


def _decode_response_payload(response: BaseResponse) -> dict[str, Any]:
    if response.raw is None or response.raw.content is None:
        raise LarkBotInfoError("bot info response did not include a raw JSON body")

    try:
        payload = json.loads(response.raw.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LarkBotInfoError("bot info response body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise LarkBotInfoError("bot info response body is not a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
