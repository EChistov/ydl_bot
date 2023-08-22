import os
import queue
import threading
from typing import TypedDict, Optional

import yt_dlp as youtube_dl
from telebot import logger as log, TeleBot
from telebot.types import Message
from yt_dlp import FFmpegExtractAudioPP

from lang_support import BOT_MSG
from msg_editor import size_analyse_thread
from utils import retry, choose_language as lang, send_audio_file


class MyYoutubeDL(youtube_dl.YoutubeDL):
    def run_all_pps(self, key, info, *, additional_pps=None):
        return super().run_all_pps(key, info, additional_pps=None)

    def download(self, url_list):
        log.info(f'Downloading {url_list}')
        return super().download(url_list)


class InfoYDLObj(TypedDict):
    duration: int
    filename: str


class ControlledPostProcessor(FFmpegExtractAudioPP):
    """Set bitrate in super func, get Finish Status of FFmgegPostProcessing and sent audio file"""

    def __init__(self, *args, message: Message, bot: TeleBot, user_lang_code=None, msg_queue: queue.Queue, **kwargs):
        super().__init__(*args, **kwargs)
        self.msg_queue = msg_queue
        self.run_thread = True
        self.bot = bot
        try:
            self.preferredquality = int(kwargs['preferredquality'])
        except Exception as e:
            log.exception(e)
            self.run_thread = False
        self.message = message
        if user_lang_code:
            self.message.from_user.language_code = user_lang_code

    def run(self, info):
        file_name, duration = self._get_file_name_and_duration(info)
        exit_event = None
        if self.run_thread:
            exit_event = threading.Event()

            pp_thread = threading.Thread(target=size_analyse_thread,
                                         args=(file_name, duration, self.preferredquality, self.message, self.msg_queue,
                                               exit_event))
            pp_thread.start()
        _a, _b = super().run(info)
        if exit_event is not None:
            exit_event.set()
        retry(send_audio_file)(self.bot, _b['filepath'], self.message, gen_answer=True,
                               tg_message_obj=self.message,
                               tg_error_msg=BOT_MSG[lang(self.message)]['file_sending_error'])
        return _a, _b

    def _get_file_name_and_duration(self, info: InfoYDLObj):
        file_name: Optional[str] = None
        duration: Optional[int] = None
        if info['filename'] is not None:
            file_name = os.path.splitext(info['filename'])[0]
        if info['duration'] is not None:
            duration = info['duration']
        if not (file_name and duration):
            self.run_thread = False
        return file_name, duration
