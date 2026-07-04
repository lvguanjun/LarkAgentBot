from __future__ import annotations

from lark_agent.config import AppConfig
from lark_agent.llm_client import LLMClient
from lark_agent.project import ProjectStore
from lark_agent.router import MessageRouter
from lark_agent.transport.base import IncomingMessage, MessageSender


class BotApp:
    def __init__(
        self,
        config: AppConfig,
        *,
        sender: MessageSender,
        llm_client: LLMClient,
        router: MessageRouter | None = None,
        project_store: ProjectStore | None = None,
    ) -> None:
        self.config = config
        self.sender = sender
        self.llm_client = llm_client
        self.router = router or MessageRouter(config.lark.bot_id)
        self.project_store = project_store or ProjectStore(
            config.data_dir,
            max_messages=config.conversation.max_messages,
        )

    async def handle_message(self, message: IncomingMessage) -> str | None:
        if not self.router.should_respond(message):
            return None
        if self.router.is_command(message):
            return None

        project = self.project_store.get_project(message.chat_id)
        thread_id = self.router.get_thread_id(message)
        conversation = project.get_conversation(thread_id)

        conversation.append(message.to_openai_message())
        context = conversation.get_context()
        reply = await self.llm_client.complete(project.get_agents_md(), context)
        conversation.append({"role": "assistant", "content": reply})

        await self.sender.send_text(
            message.chat_id,
            reply,
            root_id=message.root_id,
            reply_to_message_id=message.message_id,
        )

        if message.chat_type == "group" and message.root_id:
            self.router.mark_thread_activated(message.chat_id, message.root_id)

        return reply
