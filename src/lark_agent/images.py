from __future__ import annotations

import base64
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from lark_agent.conversation import Message
from lark_agent.transport.base import (
    ContentPart,
    DownloadedImage,
    ImageDownloader,
    ImagePart,
    content_part_text,
)


IMAGE_DOWNLOAD_FAILED_TEXT = "[用户发送了一张图片，但图片下载失败]"
IMAGE_UNAVAILABLE_TEXT = "[用户发送了一张图片，但图片不可用]"
IMAGE_REF_TYPE = "image_ref"
IMAGE_URL_TYPE = "image_url"
TEXT_TYPE = "text"
ATTACHMENTS_DIR = "attachments"
IMAGES_DIR = "images"


async def build_user_message(
    *,
    message_id: str,
    parts: list[ContentPart],
    project_path: Path,
    image_downloader: ImageDownloader | None,
) -> Message:
    content: list[dict[str, Any]] = []
    has_image_ref = False

    for part in parts:
        if isinstance(part, ImagePart):
            image_ref = await _download_and_store_image(
                message_id=message_id,
                part=part,
                project_path=project_path,
                image_downloader=image_downloader,
            )
            if image_ref is None:
                _append_text(content, IMAGE_DOWNLOAD_FAILED_TEXT)
                continue

            content.append({"type": IMAGE_REF_TYPE, IMAGE_REF_TYPE: image_ref})
            has_image_ref = True
            continue

        _append_text(content, content_part_text(part))

    if has_image_ref:
        return {"role": "user", "content": content}
    return {"role": "user", "content": _content_text(content)}


def expand_images_for_llm(messages: list[Message], *, project_path: Path) -> list[Message]:
    return [_expand_message_images(message, project_path=project_path) for message in messages]


async def _download_and_store_image(
    *,
    message_id: str,
    part: ImagePart,
    project_path: Path,
    image_downloader: ImageDownloader | None,
) -> dict[str, str] | None:
    if image_downloader is None:
        return None

    try:
        image = await image_downloader.download_image(message_id, part.file_key)
    except Exception:
        return None

    if not image.data:
        return None

    mime_type = _image_mime_type(image)
    relative_path = _store_image(
        project_path=project_path,
        message_id=message_id,
        file_key=part.file_key,
        image=image,
    )
    return {
        "path": relative_path,
        "mime_type": mime_type,
        "file_key": part.file_key,
        "alt_text": part.alt_text,
    }


def _store_image(
    *,
    project_path: Path,
    message_id: str,
    file_key: str,
    image: DownloadedImage,
) -> str:
    digest = hashlib.sha256()
    digest.update(message_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(file_key.encode("utf-8"))
    digest.update(b"\0")
    digest.update(image.data)
    name = f"{digest.hexdigest()}.bin"
    relative_path = Path(ATTACHMENTS_DIR) / IMAGES_DIR / name
    path = project_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image.data)
    return relative_path.as_posix()


def _expand_message_images(message: Message, *, project_path: Path) -> Message:
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)

    expanded: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") != IMAGE_REF_TYPE:
            expanded.append(dict(part))
            continue

        image_ref = part.get(IMAGE_REF_TYPE)
        image_url = _image_ref_data_url(image_ref, project_path=project_path)
        if image_url is None:
            _append_text(expanded, IMAGE_UNAVAILABLE_TEXT)
            continue
        expanded.append({"type": IMAGE_URL_TYPE, IMAGE_URL_TYPE: {"url": image_url}})

    expanded_message = dict(message)
    expanded_message["content"] = expanded
    return expanded_message


def _image_ref_data_url(image_ref: Any, *, project_path: Path) -> str | None:
    if not isinstance(image_ref, dict):
        return None

    path_value = image_ref.get("path")
    if not isinstance(path_value, str) or not path_value:
        return None

    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        return None

    image_path = project_path / path
    try:
        data = image_path.read_bytes()
    except OSError:
        return None

    if not data:
        return None

    mime_type = image_ref.get("mime_type")
    if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
        mime_type = _guess_mime_type(data=data, file_name=image_path.name)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _append_text(content: list[dict[str, Any]], text: str) -> None:
    if not text:
        return
    if content and content[-1].get("type") == TEXT_TYPE:
        content[-1]["text"] = f"{content[-1].get('text', '')}{text}"
        return
    content.append({"type": TEXT_TYPE, "text": text})


def _content_text(content: list[dict[str, Any]]) -> str:
    return "".join(
        part.get("text", "") for part in content if part.get("type") == TEXT_TYPE
    ).strip()


def _image_mime_type(image: DownloadedImage) -> str:
    if image.mime_type.startswith("image/"):
        return image.mime_type
    return _guess_mime_type(data=image.data, file_name=image.file_name)


def _guess_mime_type(*, data: bytes, file_name: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    guessed, _ = mimetypes.guess_type(file_name)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"
