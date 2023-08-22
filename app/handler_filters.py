from queue import Queue, Empty
import threading
from typing import List

import sqlalchemy
from sqlalchemy import select
from telebot import custom_filters
from telebot.types import Message
from telebot import logger as log
from validators import url

from database.async_db_access import DBMessage, DBCommand
from database.schema import UserPermissions
from config_parse import Config, BotConfig

cfg: BotConfig = Config()


class IsUser(custom_filters.SimpleCustomFilter):
    key = 'is_user'
    lock = threading.Lock()
    USER_ID_LIST = set()
    _instance = None
    _db_query = select(UserPermissions.user_id).where(UserPermissions.is_user.is_(True))

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(IsUser, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_input_queue: Queue, *args, **kwargs):
        self.db_input_queue = db_input_queue
        if self.db_input_queue is None:
            raise TypeError("db_input_queue should be set")
        self.db_input_queue = db_input_queue
        super().__init__(*args, **kwargs)

    def check(self, message: Message) -> bool:
        """Checks permission of usage main bot's function - downloading, also validates incoming message"""

        # if message.content_type != 'text':
        #     return False
        # if not url(message.text):
        #     return False
        if message.from_user.id in cfg.main.super_admin_list:
            return True
        with self.lock:
            return message.from_user.id in self.USER_ID_LIST

    def update_users(self):
        """Concurrently safe Update list of users from user_permissions table"""

        results_queue = Queue()

        # Send request to DB Thread
        self.db_input_queue.put(DBMessage(command=DBCommand.Select, result_queue=results_queue, execute_obj=self._db_query))
        try:
            results: List[sqlalchemy.engine.Row] = results_queue.get(block=True, timeout=10)
        except Empty:
            with self.lock:
                self.USER_ID_LIST = set()
                log.error("Updating users list timeout exception")
                return
        else:
            with self.lock:
                self.USER_ID_LIST = set(x[0] for x in results)
                log.info(f'{self.key} set has been updated and contain {len(self.USER_ID_LIST)} element(s)')


class IsAdmin(IsUser):
    key = 'is_admin'
    _db_query = select(UserPermissions.user_id).where(UserPermissions.is_admin.is_(True))
    # Reset singleton of parent class
    _instance = None








