from lark_agent.router import MAIN_THREAD_ID, MessageRouter
from lark_agent.transport.base import ChatType, IncomingMessage, TextPart


def make_message(
    *,
    chat_type: ChatType = "group",
    mentions: list[str] | None = None,
    root_id: str | None = None,
    text: str = "hello",
) -> IncomingMessage:
    return IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type=chat_type,
        sender_id="user-1",
        root_id=root_id,
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
    router.mark_thread_activated("chat-1", "root-1")

    assert router.should_respond(make_message(root_id="root-1")) is True
    assert router.should_respond(make_message(root_id="root-2")) is False


def test_thread_id_resolution() -> None:
    router = MessageRouter("bot-1")

    assert router.get_thread_id(make_message(chat_type="p2p")) == "chat-1"
    assert router.get_thread_id(make_message(root_id="root-1")) == "root-1"
    assert router.get_thread_id(make_message()) == MAIN_THREAD_ID


def test_command_detection_respects_chat_type_rules() -> None:
    router = MessageRouter("bot-1")

    assert router.is_command(make_message(chat_type="p2p", text="/help")) is True
    assert router.is_command(make_message(text="/help", mentions=[])) is False
    assert router.is_command(make_message(text="/help", mentions=["bot-1"])) is True
