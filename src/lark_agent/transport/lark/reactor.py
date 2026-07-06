from __future__ import annotations

import logging
from typing import Any

from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    DeleteMessageReactionRequest,
    Emoji,
)

logger = logging.getLogger(__name__)


class LarkMessageReactor:
    def __init__(self, client: Any) -> None:
        self._reaction_api = client.im.v1.message_reaction

    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        try:
            emoji = Emoji.builder().emoji_type(emoji_type).build()
            body = CreateMessageReactionRequestBody.builder().reaction_type(emoji).build()
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            response = await self._reaction_api.acreate(request)
            if not _is_success(response):
                logger.warning(
                    "Failed to add reaction %s to %s: code=%s msg=%s",
                    emoji_type,
                    message_id,
                    getattr(response, "code", None),
                    getattr(response, "msg", None),
                )
                return None
            data = getattr(response, "data", None)
            reaction_id = getattr(data, "reaction_id", None)
            return reaction_id if isinstance(reaction_id, str) and reaction_id else None
        except Exception:
            logger.warning(
                "Exception adding reaction %s to %s", emoji_type, message_id, exc_info=True
            )
            return None

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        try:
            request = (
                DeleteMessageReactionRequest.builder()
                .message_id(message_id)
                .reaction_id(reaction_id)
                .build()
            )
            response = await self._reaction_api.adelete(request)
            if not _is_success(response):
                logger.warning(
                    "Failed to remove reaction %s from %s: code=%s msg=%s",
                    reaction_id,
                    message_id,
                    getattr(response, "code", None),
                    getattr(response, "msg", None),
                )
        except Exception:
            logger.warning(
                "Exception removing reaction %s from %s", reaction_id, message_id, exc_info=True
            )


def _is_success(response: Any) -> bool:
    success = getattr(response, "success", None)
    if callable(success):
        return bool(success())
    return True
