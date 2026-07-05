from lark_agent.router import MessageRouter
from lark_agent.transport.base import ChatType, ImagePart, IncomingMessage, MentionPart, TextPart


def make_message(
    *,
    chat_type: ChatType = "group",
    mentions: list[str] | None = None,
    root_id: str | None = None,
    thread_id: str | None = None,
    text: str = "hello",
) -> IncomingMessage:
    return IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type=chat_type,
        sender_id="user-1",
        root_id=root_id,
        thread_id=thread_id,
        mentions=mentions or [],
        content=[TextPart(text)],
    )


def test_group_requires_mention_in_main_conversation() -> None:
    router = MessageRouter("bot-1")

    assert router.should_respond(make_message(mentions=[])) is False
    assert router.should_respond(make_message(mentions=["bot-1"])) is True


def test_private_chat_always_responds() -> None:
    router = MessageRouter("bot-1")

    assert router.should_respond(make_message(chat_type="p2p")) is True


def test_activated_thread_auto_responds_without_mention() -> None:
    router = MessageRouter("bot-1")
    router.mark_thread_activated("chat-1", "omt-1")

    assert router.should_respond(make_message(root_id="root-1", thread_id="omt-1")) is True
    assert router.should_respond(make_message(root_id="root-1")) is False
    assert router.should_respond(make_message(root_id="root-2", thread_id="omt-2")) is False


def test_thread_id_resolution() -> None:
    router = MessageRouter("bot-1")

    assert router.get_existing_thread_id(make_message(thread_id="omt-1")) == "omt-1"
    assert router.get_existing_thread_id(make_message(chat_type="p2p")) is None
    assert router.get_existing_thread_id(make_message(root_id="root-1")) is None


def test_command_detection_respects_chat_type_rules() -> None:
    router = MessageRouter("bot-1")

    assert router.is_command(make_message(chat_type="p2p", text="/help")) is True
    assert router.is_command(make_message(text="/help", mentions=[])) is False
    assert router.is_command(make_message(text="/help", mentions=["bot-1"])) is True


def test_group_command_detection_strips_leading_lark_mention_token() -> None:
    router = MessageRouter("bot-1")
    message = make_message(text="@_user_1 /help", mentions=["bot-1"])

    assert router.is_command(message) is True
    assert router.normalized_text_content(message) == "/help"


def test_group_normalized_text_strips_leading_post_mention_before_image() -> None:
    router = MessageRouter("bot-1")
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=["bot-1"],
        content=[
            MentionPart(user_id="@_user_1", user_name="MiMi"),
            TextPart(" "),
            ImagePart(file_key="img-1"),
            TextPart("这张图说了啥，"),
        ],
    )

    assert router.normalized_text_content(message) == "[用户发送了一张图片]这张图说了啥，"


def test_group_normalized_text_keeps_middle_mention() -> None:
    router = MessageRouter("bot-1")
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=["bot-1"],
        content=[
            TextPart("@_user_1 请问 "),
            MentionPart(user_id="@_user_2", user_name="Alice"),
            TextPart(" 怎么看？"),
        ],
    )

    assert router.normalized_text_content(message) == "请问 Alice 怎么看？"
