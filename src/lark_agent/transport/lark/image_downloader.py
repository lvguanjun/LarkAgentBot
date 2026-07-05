from __future__ import annotations

from typing import Any

from lark_oapi.api.im.v1 import GetImageRequest, GetMessageResourceRequest

from lark_agent.transport.base import DownloadedImage


class LarkImageDownloadError(RuntimeError):
    """Raised when Feishu/Lark image download fails."""


class LarkImageDownloader:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def download_image(self, message_id: str, file_key: str) -> DownloadedImage:
        errors: list[Exception] = []

        try:
            return await self._download_image(file_key)
        except Exception as exc:
            errors.append(exc)

        try:
            return await self._download_message_resource(message_id, file_key)
        except Exception as exc:
            errors.append(exc)

        details = "; ".join(str(error) for error in errors if str(error))
        suffix = f": {details}" if details else ""
        raise LarkImageDownloadError(f"Feishu image download failed for {file_key!r}{suffix}")

    async def _download_image(self, file_key: str) -> DownloadedImage:
        request = GetImageRequest.builder().image_key(file_key).build()
        response = await self._client.im.v1.image.aget(request)
        return _downloaded_image_from_response(response)

    async def _download_message_resource(self, message_id: str, file_key: str) -> DownloadedImage:
        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type("image")
            .build()
        )
        response = await self._client.im.v1.message_resource.aget(request)
        return _downloaded_image_from_response(response)


def _downloaded_image_from_response(response: Any) -> DownloadedImage:
    success = getattr(response, "success", None)
    if callable(success) and not success():
        code = getattr(response, "code", None)
        message = getattr(response, "msg", None) or "unknown error"
        raise LarkImageDownloadError(f"code={code}, msg={message}")

    file_obj = getattr(response, "file", None)
    read = getattr(file_obj, "read", None)
    if not callable(read):
        raise LarkImageDownloadError("response did not include image bytes")

    data = read()
    if not isinstance(data, bytes) or not data:
        raise LarkImageDownloadError("response image bytes are empty")

    return DownloadedImage(
        data=data,
        mime_type=_response_content_type(response),
        file_name=_string_attr(response, "file_name"),
    )


def _response_content_type(response: Any) -> str:
    raw = getattr(response, "raw", None)
    headers = getattr(raw, "headers", None)
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "content-type" and isinstance(value, str):
            return value.split(";", maxsplit=1)[0].strip()
    return ""


def _string_attr(obj: Any, name: str) -> str:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else ""
