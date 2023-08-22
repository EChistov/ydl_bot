import os
import re
import time
from typing import Optional, Tuple, Sequence, List

from telebot import TeleBot
from telebot import logger as log
from telebot.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from config_parse import Config, BotConfig
from lang_support import BOT_MSG

cfg: BotConfig = Config()


def retry(fn):
    """Decorator for making separate attempts of using func. If somthing goes wrong, lets try again :)"""

    def wrap(*args, gen_answer=None, bot_obj=None, tg_message_obj=None, tg_error_msg=None, retry_delay=1.0,
             max_attempt=cfg.advanced.max_attempt,
             **kwargs):
        attempt = 0
        while attempt < max_attempt:
            attempt += 1
            log_debug(f'Starting wrap with fn:{str(fn)}, attempt {attempt}')
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                log.info(f'Attempt: {attempt} unsuccessful')
                log.exception(e)
                time.sleep(retry_delay)
                continue
            else:
                return result
        if gen_answer:
            bot_answer_with_error(bot_obj, tg_message_obj, tg_error_msg)

    return wrap


def bot_answer_with_error(bot_obj: TeleBot, message: Message, msg: str) -> None:
    """Send 'bad news' to telegram user"""
    log.error(msg)
    try:
        bot_obj.send_message(message.chat.id, msg)
    except Exception as e:
        log.exception(e)


def log_debug(*msg: object):
    """Just pretty debug separator for long messages"""
    log.debug('-----------------------------------------------------------')
    log.debug(''.join(map(str, msg)))
    log.debug('-----------------------------------------------------------')


def choose_language(*messages: Message) -> str:
    """Localisation helper, default: EN"""
    for message in messages:
        if message.from_user.language_code:
            log.debug(message.from_user.language_code)
            if cfg.main.lang == 'auto':
                if message.from_user.language_code.upper() in BOT_MSG:
                    return message.from_user.language_code.upper()
            else:
                return cfg.main.lang
    return 'EN'


def calculate_mp3_bitrate(video_duration: int) -> int:
    """Calculate a bitrate for telegram_API-50MB sending limit"""

    log.info(f'Video duration is: {video_duration} sec')
    bitrate_to_set = 0
    for bitrate in cfg.advanced.use_bitrate:
        if potential_file_size(video_duration, bitrate) < 50:
            bitrate_to_set = bitrate
            break
    log.info(f'Bitrate will be: {bitrate_to_set}')
    return bitrate_to_set


def file_name_manipulate(file_name: str) -> str:
    """Cut emoji from file-names"""
    emoji_pattern = re.compile("["
                               u"\U0001F600-\U0001F64F"  # emoticons
                               u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                               u"\U0001F680-\U0001F6FF"  # transport & map symbols
                               u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                               "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', file_name)


def potential_file_size(duration, potential_bitrate: int):
    """Calculate potential bitrate, mb wrong, but close to reality (tested via experiments)"""
    return duration * potential_bitrate / 8 / 1024


def suppress_unknown(s: str) -> str:
    """Don't show 'Unknown' string in time-left string"""
    if s == "Unknown":
        return ""
    return s


def draw_progress_bar(p: int) -> str:
    """Draw Progress Bar"""
    if 0 <= p <= 100:
        progress = p // 5
        return '■' * progress + '□' * (20 - progress) + f' {p:3}%'
    else:
        return ''


def ydl_percent_str_to_int(ydl_status_str: str) -> int:
    """Make percentage number from  bar from ydl_status_str ' 89.4%' (space included)"""
    try:
        p = int(float(ydl_status_str.strip().replace('%', '')))
    except Exception as e:
        log.exception(e)
        return -1
    else:
        return p


def send_audio_file(bot: TeleBot, file_path: str, message: Message, delete_file=cfg.advanced.auto_delete_files,
                    send_timeout=cfg.advanced.send_timeout):
    if not os.path.exists(file_path):
        raise FileNotFoundError
    file_size = os.path.getsize(file_path) / 1024 ** 2
    msg_to_delete = bot.send_message(message.chat.id,
                                     f'{BOT_MSG[choose_language(message)]["file_sending_started"]}:'
                                     f'{os.path.basename(file_path)} - {file_size:.2f} MB')
    try:
        with open(file_path, 'rb') as file_object:
            msg = bot.send_audio(chat_id=message.chat.id, audio=file_object, timeout=send_timeout)
        if delete_file and msg:
            delete_file_from_server(file_path)
    finally:
        bot.delete_message(message.chat.id, msg_to_delete.message_id)


def delete_file_from_server(file_path: str) -> None:
    try:
        os.remove(file_path)
    except Exception as e:
        log.exception(e)


def make_back_button(target: str) -> InlineKeyboardButton:
    return InlineKeyboardButton('<- Back', callback_data=target)


def specify_user_privilege_msg(user_name: str, language: str, is_admin: bool, is_user: bool) -> str:
    language = language.upper()
    if cfg.main.lang == 'auto':
        if language not in BOT_MSG:
            language = 'EN'
    else:
        language = cfg.main.lang.upper()
    if is_admin:
        msg = BOT_MSG[language]['admin_granted']
    elif is_user:
        msg = BOT_MSG[language]['user_granted']
    else:
        msg = BOT_MSG[language]['flush_privileges']
    return f'{user_name}, {msg}'


class AdmMenuState(str):
    exit = 'admin-menu-exit'
    show_history = 'admin-menu-show-stat'
    user_control = 'admin-menu-user-control'
    delete_all_users = 'admin-menu-delete-all-users'
    edit_users = 'admin-menu-edit-users'
    back_to_main = 'admin-menu-back-to-main'
    edit_user_privilege = 'admin-menu-edit-user-privilege'
    accept_or_decline = 'admin-menu-accept-decline'

    @staticmethod
    def delete_callback_data_prefix(prefix, callback_data) -> str:
        return callback_data[len(prefix):]


def get_main_admin_menu() -> InlineKeyboardMarkup:
    menu = InlineKeyboardMarkup(row_width=2)
    # back = InlineKeyboardButton('<- Back', callback_data=AdmMenuState.back_to_main)
    button_exit = InlineKeyboardButton('Exit', callback_data=AdmMenuState.exit)
    button_users_ad = InlineKeyboardButton('Show History', callback_data=AdmMenuState.show_history)
    button_admin_ad = InlineKeyboardButton('Add / Delete User', callback_data=AdmMenuState.user_control)
    menu.add(button_users_ad, button_admin_ad, button_exit)
    return menu


def make_user_edit_buttons(user_id: int, is_admin: Optional[bool], is_user: Optional[bool]) -> (
        Tuple)[InlineKeyboardButton, InlineKeyboardButton]:
    if is_admin:
        is_admin_label = 'Withdraw Admin'
    else:
        is_admin_label = 'Grant Admin'
    if is_user:
        is_user_label = 'Withdraw User'
    else:
        is_user_label = 'Grant User'
    return (InlineKeyboardButton(text=is_admin_label, callback_data=AdmMenuState.edit_user_privilege +
                                                                    f'{user_id}-{is_admin_label.replace(" ", "")}'),
            InlineKeyboardButton(text=is_user_label, callback_data=AdmMenuState.edit_user_privilege +
                                                                   f'{user_id}-{is_user_label.replace(" ", "")}'))


def prepare_user_history_str_message(message: Message, entries: Sequence, count: int, current_offset: int) -> str:
    m = f'History of downloading (total {count}): \n'
    if len(entries) == 0:
        return BOT_MSG[choose_language(message)]['no_history_answer']
    for res in entries:
        current_offset += 1
        m += f'#{current_offset} <b>{res[1]}</b> [{res[0]}] {res[3].strftime("%d.%m.%Y, %H:%M:%S")}\n{res[2]}\n\n'
    return m


def normalize_count_result(sequence_result: Sequence) -> Optional[int]:
    try:
        count = sequence_result[0][0]
    except IndexError as e:
        log.error("Value error exception during normalize count result")
        log.exception(e)
        return None
    except Exception as e:
        log.exception(e)
    else:
        if isinstance(count, int):
            return count
        log.error("normalize_count_result: result is not int")
        return None


def get_offset_and_id_list(call: CallbackQuery, prefix='') -> (int, List[int]):
    offset = 0
    id_list: List[int] = []
    incoming_data = call.data[len(prefix):]
    if len(incoming_data) == 0:
        return offset, id_list
    incoming_data_items = incoming_data.split('-')
    offset = int(incoming_data_items[0])
    try:
        id_list = [int(x) for x in incoming_data_items[1:]]
    except ValueError:
        pass
    return offset, id_list
