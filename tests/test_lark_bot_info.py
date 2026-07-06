from __future__ import annotations

import json
from typing import Any

import pytest
from lark_oapi.core import AccessTokenType, HttpMethod
from lark_oapi.core.model import BaseRequest, BaseResponse, RawResponse

from lark_agent.config import AppConfig, LarkConfig
from lark_agent.transport.lark.bot_info import (
    BOT_INFO_URI,
    LarkBotInfo,
    LarkBotInfoError,
    build_bot_info_request,
    fetch_lark_bot_info,
    validate_lark_app_credentials,
)


class FakeLarkClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[BaseRequest] = []

    def request(self, request: BaseRequest) -> BaseResponse:
        self.requests.append(request)
        raw = RawResponse()
        raw.set_content_type("application/json")
        raw.status_code = 200
        raw.content = json.dumps(self.payload).encode("utf-8")
        response = BaseResponse()
        response.raw = raw
        return response


def test_build_bot_info_request_uses_tenant_token() -> None:
    request = build_bot_info_request()

    assert request.http_method is HttpMethod.GET
    assert request.uri == BOT_INFO_URI
    assert request.token_types == {AccessTokenType.TENANT}


def test_fetch_lark_bot_info_returns_open_id() -> None:
    client = FakeLarkClient(
        {
            "code": 0,
            "msg": "ok",
            "bot": {
                "activate_status": 2,
                "app_name": "agent",
                "avatar_url": "https://example.test/avatar.png",
                "ip_white_list": ["127.0.0.1"],
                "open_id": "ou_bot",
            },
        }
    )

    bot_info = fetch_lark_bot_info(client)

    assert bot_info == LarkBotInfo(
        activate_status=2,
        app_name="agent",
        avatar_url="https://example.test/avatar.png",
        ip_white_list=("127.0.0.1",),
        open_id="ou_bot",
    )
    assert client.requests[0].uri == BOT_INFO_URI


def test_fetch_lark_bot_info_raises_for_nonzero_code() -> None:
    client = FakeLarkClient({"code": 999, "msg": "failed"})

    with pytest.raises(LarkBotInfoError, match="code=999"):
        fetch_lark_bot_info(client)


def test_fetch_lark_bot_info_requires_open_id() -> None:
    client = FakeLarkClient({"code": 0, "msg": "ok", "bot": {}})

    with pytest.raises(LarkBotInfoError, match=r"bot\.open_id"):
        fetch_lark_bot_info(client)


def test_validate_lark_app_credentials_does_not_require_bot_id() -> None:
    config = AppConfig(lark=LarkConfig(app_id="cli_xxx", app_secret="secret"))

    validate_lark_app_credentials(config)


def test_validate_lark_app_credentials_requires_app_id_and_secret() -> None:
    config = AppConfig(lark=LarkConfig(app_id="cli_xxx"))

    with pytest.raises(ValueError, match=r"lark\.app_secret"):
        validate_lark_app_credentials(config)
