from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

import lark_oapi as lark

from lark_agent.app import BotApp
from lark_agent.config import AppConfig, LarkConfig, load_config
from lark_agent.llm_client import LLMClient
from lark_agent.transport.lark.bot_info import fetch_lark_bot_info
from lark_agent.transport.lark.card_streamer import LarkCardStreamer
from lark_agent.transport.lark.image_downloader import LarkImageDownloader
from lark_agent.transport.lark.reactor import LarkMessageReactor
from lark_agent.transport.lark.runner import LarkWebSocketBotRunner
from lark_agent.transport.lark.sender import LarkMessageSender


def configure_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger("lark_agent")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] [%(asctime)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)


def validate_lark_config(config: AppConfig) -> None:
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


def build_runner(config: AppConfig) -> LarkWebSocketBotRunner:
    validate_lark_config(config)
    lark_client = (
        lark.Client.builder().app_id(config.lark.app_id).app_secret(config.lark.app_secret).build()
    )
    bot_info = fetch_lark_bot_info(lark_client)
    runtime_config = config.model_copy(
        update={
            "lark": LarkConfig(
                app_id=config.lark.app_id,
                app_secret=config.lark.app_secret,
                bot_id=bot_info.open_id,
            )
        }
    )
    sender = LarkMessageSender(lark_client)
    image_downloader = LarkImageDownloader(lark_client)
    reactor = LarkMessageReactor(lark_client)
    card_streamer = LarkCardStreamer(lark_client)
    app = BotApp(
        runtime_config,
        sender=sender,
        llm_client=LLMClient.from_config(runtime_config.llm),
        image_downloader=image_downloader,
        reactor=reactor,
        card_streamer=card_streamer,
    )
    return LarkWebSocketBotRunner(
        app_id=runtime_config.lark.app_id,
        app_secret=runtime_config.lark.app_secret,
        app=app,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Lark Agent Feishu WebSocket bot.")
    parser.parse_args(argv)

    configure_logging()
    config = load_config()
    build_runner(config).start()


if __name__ == "__main__":
    main()
