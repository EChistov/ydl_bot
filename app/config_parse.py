import json
import os
import sys
from logging import INFO
from typing import List, Set

from pydantic import BaseModel
from pydantic import ValidationError
from pydantic.types import constr
from telebot import TeleBot
from telebot import logger as log
from telebot.types import Message

log.setLevel(INFO)


class MainConfig(BaseModel):
    telegram_token: str
    super_admin_list: Set[int]
    lang: constr(pattern="^(auto|RU|EN)$")
    mp3_dir: str


class AdvancedConfig(BaseModel):
    use_bitrate: List[int]
    max_attempt: int
    send_timeout: int
    auto_delete_files: bool
    msg_thread_count: int
    history_entries_on_page: int
    users_on_page: int


class BotConfig(BaseModel):
    main: MainConfig
    advanced: AdvancedConfig


class Config(object):
    _instance = None

    def __new__(cls, **kwargs):
        if not cls._instance:
            try:
                with open(cls._get_config_path(), "r") as file:
                    data = json.load(file)
            except FileNotFoundError:
                log.error("Config file not found")
                sys.exit(1)
            except Exception as e:
                log.exception(e)
            else:
                try:
                    cls._instance = BotConfig(**data)
                except ValidationError as e:
                    log.error('Config validation Error')
                    log.exception(e)
                    sys.exit(1)
                except Exception as e:
                    log.exception(e)
                    sys.exit(1)

                telegram_token = os.getenv('TELEGRAM_TOKEN')
                if telegram_token:
                    cls._instance.main.telegram_token = telegram_token
                # ENV("BOT_SUPERADMIN_LIST") > JSON config > empty (if empty -> run Init mode)
                cls._check_admin_list()

        return cls._instance

    @classmethod
    def _get_config_path(cls) -> str:
        """If ENV config path was not specified will be used a default path"""
        user_config_path = os.getenv('BOT_CONFIG_PATH')
        if user_config_path:
            return user_config_path
        if os.path.isfile('../bot_conf.json'):
            return '../bot_conf.json'
        else:
            log.critical("Can't find config file")
            raise Exception("Config file doesn't exist")

    @classmethod
    def _check_admin_list(cls):
        if cls._instance.main.super_admin_list is None or len(cls._instance.main.super_admin_list) == 0:
            env_admin_str: str = os.getenv('BOT_SUPERADMIN_LIST')
            if env_admin_str is None or env_admin_str == "":
                # Start init_mode do get telegram_user_id
                cls._run_init_mode()
                sys.exit(1)
            env_admin_list: list = env_admin_str.strip().split(',')
            cls._instance.main.super_admin_list = set(int(user_id) for user_id in env_admin_list)

    @classmethod
    def _run_init_mode(cls):
        """Shows only UserID"""
        log.info('Start Init mode')
        bot = TeleBot(cls._instance.main.telegram_token)

        @bot.message_handler(func=lambda m: True)
        def get_id(message: Message):
            log.info(f'Receive a message from id: {message.from_user.id}')
            bot.send_message(message.chat.id, f'ID:{message.from_user.id}')

        bot.infinity_polling()
