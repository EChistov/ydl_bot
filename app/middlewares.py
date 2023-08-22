import queue
import threading
from typing import Dict, List

import sqlalchemy
from sqlalchemy import select, update
from telebot import BaseMiddleware, logger as log
from telebot.types import Message

from database.async_db_access import DBMessage, DBCommand
from database.schema import TelegramUser


class UserCollectMiddleware(BaseMiddleware):
    """Middleware for updating user information (store actual user information)"""

    KNOWN_USERS_DICT: Dict[int, TelegramUser] = {}
    loc = threading.Lock()

    def __init__(self, db_request_queue: queue.Queue):
        super().__init__()
        self.db_request_queue = db_request_queue
        self.update_types = ['message']
        self.update_known_list()

    def pre_process(self, message: Message, data):
        if message.from_user.id not in self.KNOWN_USERS_DICT:
            self._create_user(message)
            return
        if not self._compare(message):
            self._update_user(message)
        else:
            log.debug(f'User {message.from_user.id} has been checked and there are no changes')

    def post_process(self, message, data, exception):
        pass

    def update_known_list(self):
        log.debug(f'Func {self.update_known_list.__name__} has been run')
        query = select(TelegramUser)
        result_que = queue.Queue()
        self.db_request_queue.put(DBMessage(command=DBCommand.Select, execute_obj=query, result_queue=result_que),
                                  block=False)
        try:
            result: List[sqlalchemy.engine.Row] = result_que.get(timeout=4)
        except queue.Empty:
            log.error(f"Middleware db result queue timeout")
            return
        else:
            with self.loc:
                self.KNOWN_USERS_DICT.clear()
                for user in result:
                    self.KNOWN_USERS_DICT[user[0].id] = user[0]
                log.info(f'Known user dict has been updated and contain {len(self.KNOWN_USERS_DICT)} users')

    def _compare(self, message: Message) -> bool:
        """Make a comparison between user in the Dict and new data from incoming telegram message"""

        if message.from_user.id not in self.KNOWN_USERS_DICT:
            return False
        if message.from_user.first_name != self.KNOWN_USERS_DICT[message.from_user.id].first_name:
            return False
        if message.from_user.username != self.KNOWN_USERS_DICT[message.from_user.id].user_name:
            return False
        if message.from_user.last_name != self.KNOWN_USERS_DICT[message.from_user.id].last_name:
            return False
        if message.from_user.language_code != self.KNOWN_USERS_DICT[message.from_user.id].language_code:
            return False
        if message.from_user.is_premium != self.KNOWN_USERS_DICT[message.from_user.id].is_premium:
            return False
        if message.from_user.is_bot != self.KNOWN_USERS_DICT[message.from_user.id].is_bot:
            return False
        return True

    def _update_user(self, message: Message):
        log.info(f'User {message.from_user.id} has changes and will be updated')
        db_execute_obj = update(TelegramUser)
        user_for_update = [{
            'id': message.from_user.id,
            'is_bot': message.from_user.is_bot,
            'first_name': message.from_user.first_name,
            'user_name': message.from_user.username,
            'last_name': message.from_user.last_name,
            'language_code': message.from_user.language_code,
            'is_premium': message.from_user.is_premium,
        }]
        self.db_request_queue.put(DBMessage(user_for_update, command=DBCommand.Update, execute_obj=db_execute_obj))
        with self.loc:
            self.KNOWN_USERS_DICT[message.from_user.id] = TelegramUser.map_from_message_obj(message)

    def _create_user(self, message: Message):
        log.info(f'User {message.from_user.id} is new and will be inserted into the DB')
        user = TelegramUser.map_from_message_obj(message)
        result_queue = queue.Queue()
        self.db_request_queue.put(DBMessage(command=DBCommand.AddNew, db_obj=user, result_queue=result_queue),
                                  block=False)
        try:
            if result_queue.get(timeout=3):
                self.update_known_list()
            else:
                log.error('Somthing wrong with adding a new user')
        except queue.Empty:
            log.error('Middleware Queue timeout')
