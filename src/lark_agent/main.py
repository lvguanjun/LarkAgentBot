from __future__ import annotations

import argparse
from collections.abc import Sequence

import lark_oapi as lark

from lark_agent.app import BotApp
from lark_agent.config import AppConfig, LarkConfig, load_config
from lark_agent.llm_client import LLMClient
from lark_agent.transport.lark import LarkMessageSender, LarkWebSocketBotRunner
from lark_agent.transport.lark.bot_info import fetch_lark_bot_info


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
        lark.Client.builder()
        .app_id(config.lark.app_id)
        .app_secret(config.lark.app_secret)
        .build()
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
    app = BotApp(
        runtime_config,
        sender=sender,
        llm_client=LLMClient.from_config(runtime_config.llm),
    )
    return LarkWebSocketBotRunner(
        app_id=runtime_config.lark.app_id,
        app_secret=runtime_config.lark.app_secret,
        app=app,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Lark Agent Feishu WebSocket bot.")
    parser.parse_args(argv)

    config = load_config()
    build_runner(config).start()


if __name__ == "__main__":
    main()
