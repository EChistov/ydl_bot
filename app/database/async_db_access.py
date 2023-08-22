import queue
import threading
from enum import Enum, auto
from queue import Queue
from typing import List, Optional, Tuple, Sequence

import telebot.types
from database import db_engine
from database.schema import Base
from sqlalchemy import Executable
from sqlalchemy.orm import Session
from telebot import logger as log


class DBCommand(Enum):
    Update = auto()
    Delete = auto()
    Select = auto()
    AddNew = auto()
    Insert = auto()
    Get_Admins = auto()
    Quit = auto()


class DBMessage(object):
    def __init__(self, *args, command: DBCommand, db_obj: Base = None, execute_obj: Executable = None,
                 execute_objs: List[Executable] = None, message_obj: telebot.types.Message = None,
                 result_queue: Queue = None, **kwargs):
        self.command = command
        self.db_obj = db_obj
        self.execute_obj = execute_obj
        self.execute_objs = execute_objs
        self.message_obj = message_obj
        self.args = [*args]
        self.result_queue: Queue = result_queue
        self.kwargs = {**kwargs}


def db_consumer(q: Queue):
    log.info("BD consumer thread has started")
    while True:
        incoming_db_message: DBMessage = q.get(block=True)
        if incoming_db_message.command is DBCommand.Quit:
            log.debug('Received quit command')
            break
        if incoming_db_message.command is DBCommand.AddNew:
            log.debug('Received AddNew command')
            with Session(db_engine) as session:
                session.begin()
                try:
                    session.add(incoming_db_message.db_obj)
                except Exception as e:
                    log.exception(e)
                    session.rollback()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(False, timeout=3)
                else:
                    session.commit()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(True, timeout=3)
        if incoming_db_message.command == DBCommand.Select:
            log.debug('Received select command')
            with Session(db_engine) as session:
                session.expire_on_commit = False
                try:
                    result = session.execute(incoming_db_message.execute_obj,
                                             execution_options={"prebuffer_rows": True})

                except Exception as e:
                    log.exception(e)
                    incoming_db_message.result_queue.put(None)
                else:
                    # session.expunge_all()
                    incoming_db_message.result_queue.put(result.all(), block=False)

        if incoming_db_message.command == DBCommand.Update:
            log.debug('Received Insert command')
            with Session(db_engine) as session:
                session.begin()
                try:
                    session.execute(incoming_db_message.execute_obj, *incoming_db_message.args,
                                    execution_options={"prebuffer_rows": True})
                except Exception as e:
                    log.exception(e)
                    session.rollback()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(False, timeout=3)
                else:
                    session.commit()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(True, timeout=3)
        if incoming_db_message.command == DBCommand.Delete:
            log.debug('Received Delete command')
            with Session(db_engine) as session:
                session.begin()
                try:
                    for execute_obj in incoming_db_message.execute_objs:
                        session.execute(execute_obj, execution_options={"prebuffer_rows": True})
                except Exception as e:
                    log.exception(e)
                    session.rollback()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(False, timeout=3)
                else:
                    session.commit()
                    if incoming_db_message.result_queue is not None:
                        incoming_db_message.result_queue.put(True, timeout=3)

    log.info("BD consumer thread has closed")


def run_db_thread(consumer_func, db_queue: queue.Queue):
    db_threat = threading.Thread(target=consumer_func, args=(db_queue,))
    db_threat.start()


def delete_items_with_result(db_q: queue.Queue, queries: List[Executable]) -> bool:
    answer_queue = queue.Queue(maxsize=1)
    db_q.put(DBMessage(command=DBCommand.Delete, execute_objs=queries, result_queue=answer_queue), block=False)
    try:
        delete_result = answer_queue.get(block=True, timeout=5)
    except queue.Empty as ex:
        log.exception(ex)
        return False
    else:
        if not delete_result:
            return False
    return True


def select_entries_and_count(entries_query: Executable, count_query: Executable, db_request_queue: queue.Queue) -> (
        Optional)[Tuple[Sequence[str], Sequence[int]]]:
    entries_queue = queue.Queue()
    count_queue = queue.Queue()
    db_request_queue.put(DBMessage(command=DBCommand.Select, execute_obj=entries_query, result_queue=entries_queue),
                         block=False)
    db_request_queue.put(DBMessage(command=DBCommand.Select, execute_obj=count_query, result_queue=count_queue),
                         block=False)
    try:
        entries_result = entries_queue.get(block=True, timeout=10)
        count_result = count_queue.get(block=True, timeout=10)
    except Exception as e:
        log.exception(e)
        return None
    else:
        return entries_result, count_result
