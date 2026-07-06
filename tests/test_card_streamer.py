import json
from types import SimpleNamespace
from typing import Any

from lark_agent.transport.lark.card_streamer import LarkCardStreamer


class FakeResponse:
    def success(self) -> bool:
        return True


class FakeCardApi:
    def __init__(self) -> None:
        self.settings_requests: list[Any] = []

    async def asettings(self, request: Any) -> FakeResponse:
        self.settings_requests.append(request)
        return FakeResponse()


class FakeCardElementApi:
    pass


class FakeMessageApi:
    pass


def make_client(card_api: FakeCardApi) -> SimpleNamespace:
    return SimpleNamespace(
        cardkit=SimpleNamespace(
            v1=SimpleNamespace(
                card=card_api,
                card_element=FakeCardElementApi(),
            )
        ),
        im=SimpleNamespace(v1=SimpleNamespace(message=FakeMessageApi())),
    )


async def test_close_streaming_sets_streaming_mode_under_config() -> None:
    card_api = FakeCardApi()
    streamer = LarkCardStreamer(make_client(card_api))

    await streamer.close_streaming("card-1", 7)

    assert len(card_api.settings_requests) == 1
    request = card_api.settings_requests[0]
    assert request.card_id == "card-1"
    assert request.request_body.sequence == 7
    assert isinstance(request.request_body.settings, str)
    assert json.loads(request.request_body.settings) == {
        "config": {"streaming_mode": False}
    }
