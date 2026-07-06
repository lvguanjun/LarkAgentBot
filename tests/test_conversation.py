from pathlib import Path

from lark_agent.conversation import Conversation
from lark_agent.project import ProjectStore


def test_conversation_appends_and_reads_jsonl(tmp_path: Path) -> None:
    conversation = Conversation(tmp_path / "conversation")

    conversation.append({"role": "user", "content": "hello"})
    conversation.append({"role": "assistant", "content": "hi"})

    assert conversation.get_full_history() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_private_chat_uses_chat_id_as_conversation_id(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path, max_messages=10)
    project = store.get_project("chat-1")
    conversation = project.get_conversation("chat-1")

    conversation.append({"role": "user", "content": "hello"})

    assert (tmp_path / "groups" / "chat-1" / "conversations" / "chat-1" / "history.jsonl").exists()


def test_context_window_keeps_tool_result_pairing(tmp_path: Path) -> None:
    conversation = Conversation(tmp_path / "conversation", max_messages=2)
    conversation.append({"role": "user", "content": "old"})
    conversation.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        }
    )
    conversation.append({"role": "tool", "tool_call_id": "call-1", "content": "tool result"})
    conversation.append({"role": "assistant", "content": "final"})

    context = conversation.get_context(max_messages=2)

    assert context == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "tool result"},
        {"role": "assistant", "content": "final"},
    ]


def test_context_window_drops_orphan_leading_tool(tmp_path: Path) -> None:
    conversation = Conversation(tmp_path / "conversation", max_messages=2)
    conversation.append({"role": "tool", "tool_call_id": "missing", "content": "orphan"})
    conversation.append({"role": "user", "content": "latest"})

    assert conversation.get_context(max_messages=2) == [{"role": "user", "content": "latest"}]
