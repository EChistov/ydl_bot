import os
import queue
import threading
import time
from enum import Enum, auto

from telebot import TeleBot, logger as log
from telebot.types import Message

from config_parse import Config, BotConfig
from lang_support import BOT_MSG
from utils import retry, choose_language as lang, draw_progress_bar, ydl_percent_str_to_int, log_debug

cfg: BotConfig = Config()


class MSGCommand(Enum):
    Send = auto()
    Edit = auto()
    Delete = auto()
    Quit = auto()


class MSGMessage(object):
    """"""

    def __init__(self, *args, command: MSGCommand, message_object: Message = None,
                 message_str: str = None, with_retry=True, **kwargs):
        self.command = command
        self.message_obj = message_object
        self.message_str = message_str
        self.with_retry = with_retry
        self.args = [*args]
        self.kwargs = {**kwargs}

    def __str__(self) -> str:
        return (f'MSGMessage(Command: {self.command}, msg(message.user.id: {self.message_obj.from_user.id},'
                f'msg.text: {self.message_obj.text})')

    def __repr__(self) -> str:
        return (f'MSGMessage(Command: {self.command}, msg(message.user.id: {self.message_obj.from_user.id},'
                f'msg.text: {self.message_obj.text})')


def msg_editing_consumer(incoming_queue: queue.Queue, bot_obj: TeleBot):
    while True:
        message: MSGMessage = incoming_queue.get(block=True)
        log.debug('MSG Consumer has receive ', message)
        if message.command == MSGCommand.Quit:
            log.debug("Received Quit Msg")
            break
        if message.command == MSGCommand.Edit:
            if message.message_obj is None:
                continue
            if message.message_str is None:
                continue
            if message.with_retry:
                retry(bot_obj.edit_message_text)(text=message.message_str, chat_id=message.message_obj.chat.id,
                                                 message_id=message.message_obj.message_id, **message.kwargs)
            else:
                bot_obj.edit_message_text(text=message.message_str, chat_id=message.message_obj.chat.id,
                                          message_id=message.message_obj.message_id, **message.kwargs)
    log.info("MSG consumer thread quit")


def size_analyse_thread(file_name: str, duration: int, bitrate: int, message: Message, msg_queue: queue.Queue,
                        exit_s: threading.Event):
    """The thread which look up the size of file during converting and draw the status bar"""
    previous_message = ''
    file_name = file_name + '.mp3'
    predicted_size = duration * bitrate // 8 * 1000
    actual_size = 0
    last_call = 0.0
    message_str = BOT_MSG[lang(message)]['converting_file'] + ' ' + os.path.basename(file_name) + '\n'
    while not exit_s.is_set():
        if time.time() - last_call > 1.0:
            last_call = time.time()
            if os.path.isfile(file_name):
                try:
                    actual_size = os.path.getsize(file_name)
                except Exception as e:
                    log.error("Can't get file size")
                    log.exception(e)
                else:
                    p = actual_size * 100 // predicted_size
                    if 0 <= p <= 100:
                        message_to_edit = message_str + draw_progress_bar(p)
                        if message_to_edit != previous_message:
                            previous_message = message_to_edit
                            msg_queue.put(MSGMessage(command=MSGCommand.Edit, message_object=message,
                                                     message_str=message_to_edit, with_retry=False), block=False)
    # Try to Draw 100%
    message_to_edit = message_str + draw_progress_bar(100)
    if previous_message != message_to_edit:
        msg_queue.put(MSGMessage(command=MSGCommand.Edit, message_object=message, message_str=message_to_edit),
                      block=False)


def run_msg_threads(func, msg_queue: queue.Queue, bot: TeleBot):
    for _ in range(cfg.advanced.msg_thread_count):
        thread = threading.Thread(target=func, args=(msg_queue, bot))
        thread.start()


def close_msg_edit_thread(q: queue.Queue):
    for _ in range(cfg.advanced.msg_thread_count):
        q.put(MSGMessage(command=MSGCommand.Quit))


def get_download_progress_hook(bot_obj: TeleBot, message: Message, msg_queue: queue.Queue):
    """Make a progress hook func"""

    previous_call = 0.0

    def download_processing_hook(ydl_status):

        nonlocal previous_call
        if ydl_status['status'] == 'downloading':
            log_debug(f'bot_msg.date {message.date}, bot_msg.edit_date {message.edit_date}')
            # Suppress frequent API calls for preventing DDoS
            now = time.time()
            if now - previous_call > 1.0:
                previous_call = now
                msg_message = (BOT_MSG[lang(message)]['downloading_file'] +
                               f" {str(ydl_status['filename']).lstrip(cfg.main.mp3_dir + os.path.sep)}\n")
                status_bar = draw_progress_bar(ydl_percent_str_to_int(ydl_status['_percent_str']))
                # Send info to MSG_Thread
                message_to_edit = msg_message + status_bar
                msg_queue.put(MSGMessage(command=MSGCommand.Edit, message_object=message, message_str=message_to_edit,
                                         with_retry=False), block=False)
        if ydl_status['status'] == 'finished':
            file_tuple = os.path.split(os.path.abspath(ydl_status['filename']))
            log.info(f'Done downloading {file_tuple[1]}')
            log_debug('ydl_status: ', ydl_status)
            retry(bot_obj.edit_message_text)(chat_id=message.chat.id,
                                             text=f'{BOT_MSG[lang(message)]["downloading_done"]} {file_tuple[1]}',
                                             message_id=message.message_id)

    return download_processing_hook
