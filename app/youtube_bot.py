import logging
import os
import queue

from sqlalchemy import select, update, func, delete
from telebot import apihelper, logger, TeleBot
from telebot.types import Message, BotCommand, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from validators import url

from config_parse import Config
from database.async_db_access import DBCommand, DBMessage, db_consumer, delete_items_with_result
from database.async_db_access import run_db_thread, select_entries_and_count
from database.schema import TelegramUser, BotHistory, UserPermissions, Chat
from handler_filters import IsUser, IsAdmin
from lang_support import BOT_MSG
from middlewares import UserCollectMiddleware
from msg_editor import run_msg_threads, msg_editing_consumer, close_msg_edit_thread, get_download_progress_hook
from utils import choose_language as lang
from utils import retry, bot_answer_with_error, log_debug, calculate_mp3_bitrate, file_name_manipulate, \
    make_back_button, specify_user_privilege_msg, AdmMenuState, get_main_admin_menu, make_user_edit_buttons, \
    prepare_user_history_str_message, normalize_count_result, get_offset_and_id_list
from youtube_dl_modified_objects import MyYoutubeDL, ControlledPostProcessor

########################################################################################################################
# Config Const
BOT_VERSION = 0.1

cfg = Config()
MP3_DIR = cfg.main.mp3_dir
MAX_ATTEMPT = cfg.advanced.max_attempt
SEND_TIMEOUT = cfg.advanced.send_timeout
AUTO_DELETE_FILE = cfg.advanced.auto_delete_files
HISTORY_PER_PAGE = cfg.advanced.history_entries_on_page
USER_PER_PAGE = cfg.advanced.users_on_page

########################################################################################################################
# Setup Bot
apihelper.RETRY_ON_ERROR = True
bot = TeleBot(cfg.main.telegram_token, num_threads=10, use_class_middlewares=True)
log = logger
log.setLevel(logging.INFO)

########################################################################################################################
# Run DB Thread

db_request_queue = queue.Queue()
run_db_thread(db_consumer, db_request_queue)
########################################################################################################################
# Run MSG edit threads
msg_edit_queue = queue.Queue()
run_msg_threads(msg_editing_consumer, msg_edit_queue, bot)

########################################################################################################################

command_id = BotCommand('id', 'Shows your telegram user ID')
command_admin = BotCommand('admin', 'Shows admin menu')
bot.set_my_commands(commands=[command_id, command_admin])

########################################################################################################################
# Create and install filters.

user_filter = IsUser(db_request_queue)
user_filter.update_users()
admin_filter = IsAdmin(db_request_queue)
admin_filter.update_users()
bot.add_custom_filter(user_filter)
bot.add_custom_filter(admin_filter)

########################################################################################################################
# Middleware

bot.use_class_middlewares = True
middleware = UserCollectMiddleware(db_request_queue)
bot.setup_middleware(middleware)


########################################################################################################################
# Bot Functions


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data.startswith(AdmMenuState.accept_or_decline))
def admin_menu_accept_or_delcine(call: CallbackQuery):
    menu = InlineKeyboardMarkup(row_width=2)
    yes_button_suffix = 'yes'
    delete_action_msg = 'All data was deleted'
    delete_action_msg_err = 'Somthing goes wrong during deleting'
    callback_data_suffix = AdmMenuState.delete_callback_data_prefix(AdmMenuState.accept_or_decline, call.data)
    if callback_data_suffix.startswith('history'):
        if callback_data_suffix.endswith('yes'):
            # Delete History
            queries = [delete(BotHistory)]
            if not delete_items_with_result(db_request_queue, queries):
                delete_action_msg = delete_action_msg_err
            menu.add(make_back_button(AdmMenuState.back_to_main))
            retry(bot.edit_message_text)(delete_action_msg, call.message.chat.id, call.message.id, reply_markup=menu)
            return
        # Ask a question about history
        no_button_callback_data = AdmMenuState.show_history
        yes_button = InlineKeyboardButton('Yes', callback_data=AdmMenuState.accept_or_decline + 'history' +
                                                               yes_button_suffix)
        no_button = InlineKeyboardButton('No', callback_data=no_button_callback_data)
        menu.add(yes_button, no_button)
        retry(bot.edit_message_text)('Are you sure, you want to clear all the history?', call.message.chat.id,
                                     call.message.id, reply_markup=menu)
        return
    if callback_data_suffix.startswith('user-data'):
        if callback_data_suffix.endswith('yes'):
            # Delete user data
            answer_queue = queue.Queue(maxsize=1)
            query = select(TelegramUser.id).outerjoin(UserPermissions).where(UserPermissions.is_user.is_not(True))
            db_request_queue.put(DBMessage(command=DBCommand.Select, execute_obj=query, result_queue=answer_queue),
                                 block=False)
            try:
                result = answer_queue.get(block=True, timeout=10)
            except queue.Empty as ex:
                log.exception(ex)
            else:
                if result:
                    user_ids = result[0]
                    queries = []
                    for table in (Chat, BotHistory, UserPermissions):
                        queries.append(delete(table).where(table.user_id.in_(user_ids)))
                    queries.append(delete(TelegramUser).where(TelegramUser.id.in_(user_ids)))
                    if not delete_items_with_result(db_request_queue, queries):
                        delete_action_msg = delete_action_msg_err
            menu.add(make_back_button(AdmMenuState.back_to_main))
            retry(bot.edit_message_text)(delete_action_msg, call.message.chat.id, call.message.id, reply_markup=menu)
            middleware.update_known_list()
            return
        # Ask a question about deleting all unauthorised users
        no_button_callback_data = AdmMenuState.user_control
        yes_button = InlineKeyboardButton('Yes', callback_data=AdmMenuState.accept_or_decline + 'user-data' +
                                                               yes_button_suffix)
        no_button = InlineKeyboardButton('No', callback_data=no_button_callback_data)
        menu.add(yes_button, no_button)
        retry(bot.edit_message_text)('Are you sure, you want to delete all unauthorised users?', call.message.chat.id,
                                     call.message.id, reply_markup=menu)
        return


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data.startswith(AdmMenuState.edit_user_privilege))
def admin_menu_edit_user_privilege(call: CallbackQuery):
    callback_data_suffix = AdmMenuState.delete_callback_data_prefix(AdmMenuState.edit_user_privilege, call.data)
    if not callback_data_suffix:
        log.error("Can't edit user, somthing wrong with callback bata: ", call.data)
        return
    callback_data_list = callback_data_suffix.split('-')
    try:
        user_id = int(callback_data_list[0])
    except ValueError as exp:
        log.exception(exp)
        return
    is_admin = None
    is_user = None
    action = callback_data_list[1]
    if action == 'WithdrawAdmin':
        is_admin = False
        is_user = True
    if action == 'GrantAdmin':
        is_admin = True
        is_user = True
    if action == 'WithdrawUser':
        is_user = False
        is_admin = False
    if action == 'GrantUser':
        is_user = True
        is_admin = False

    select_query = (select(TelegramUser.id, TelegramUser.user_name, TelegramUser.first_name, TelegramUser.last_name,
                           UserPermissions.is_user, UserPermissions.is_admin, Chat.id, TelegramUser.language_code)
                    .outerjoin(UserPermissions).join(Chat)).where(TelegramUser.id == user_id)
    answer_queue = queue.Queue()
    db_request_queue.put(DBMessage(command=DBCommand.Select, execute_obj=select_query, result_queue=answer_queue),
                         block=False)
    try:
        result = answer_queue.get(block=True, timeout=10)
    except Exception as exp:
        log.exception(exp)
        return None
    else:
        if not result:
            log.error('Db receive no result during edit user request ')
            return
        entry = result[0]
        result_queue = queue.Queue()
        if entry[4] is None and entry[5] is None:
            db_request_queue.put(DBMessage(command=DBCommand.AddNew, db_obj=UserPermissions(
                user_id=user_id,
                is_user=is_user,
                is_admin=is_admin
            ), result_queue=result_queue), block=False)

        else:
            query = update(UserPermissions)
            db_request_queue.put(DBMessage(UserPermissions.get_update_data(user_id, is_admin, is_user),
                                           command=DBCommand.Update, execute_obj=query, result_queue=result_queue),
                                 block=False)

        if not result_queue.get(block=True, timeout=10):
            log.error('Db receive no result during create user_permission request ')
            return
        edit_menu = InlineKeyboardMarkup(row_width=2)
        edit_menu.add(*make_user_edit_buttons(entry[0], is_admin=is_admin, is_user=is_user))
        retry(bot.edit_message_text)(f'<b>{entry[2]}</b>[{entry[0]}]', call.message.chat.id, call.message.id,
                                     reply_markup=edit_menu, parse_mode='HTML')
        admin_filter.update_users()
        user_filter.update_users()
        retry(bot.send_message)(entry[6], specify_user_privilege_msg(entry[2], entry[7], is_admin, is_user))


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data == AdmMenuState.back_to_main)
def admin_menu_back_to_main_menu(call: CallbackQuery):
    """Return to main Admin menu"""
    retry(bot.edit_message_text)('Welcome to Admin menu!', call.message.chat.id, call.message.id,
                                 reply_markup=get_main_admin_menu())


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data == AdmMenuState.exit)
def admin_menu_exit(call: CallbackQuery):
    """Close Admin Menu"""
    bot.delete_message(call.message.chat.id, call.message.id)


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data.startswith(AdmMenuState.user_control))
def admin_menu_edit_users_submenu(call: CallbackQuery):
    suffix = call.data[len(AdmMenuState.user_control):]
    if suffix:
        for message in suffix.split('-'):
            bot.delete_message(call.message.chat.id, int(message))
    menu = InlineKeyboardMarkup(row_width=2)
    clear_all_users = InlineKeyboardButton('Delete All Unauthorised',
                                           callback_data=AdmMenuState.accept_or_decline + 'user-data')
    edit_users = InlineKeyboardButton('Edit Users', callback_data=AdmMenuState.edit_users)
    menu.add(clear_all_users, edit_users, make_back_button(AdmMenuState.back_to_main))
    bot.edit_message_text('User Privilege menu', call.message.chat.id, call.message.id, reply_markup=menu)


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data.startswith(AdmMenuState.show_history))
def admin_menu_show_history(call: CallbackQuery):
    """Admin menu callback function, process buttons pushing and show and edit the message"""

    current_offset, _ = get_offset_and_id_list(call, prefix=AdmMenuState.show_history)
    prev_offset = 0
    next_offset = current_offset + HISTORY_PER_PAGE
    if current_offset:
        prev_offset = current_offset - HISTORY_PER_PAGE

    entries_query = (select(TelegramUser.id, TelegramUser.first_name, BotHistory.msg_text, BotHistory.created_date)
    .join(BotHistory).order_by(BotHistory.created_date.desc()).offset(current_offset).limit(
        HISTORY_PER_PAGE))
    count_query = select(func.count('*')).select_from(BotHistory)
    result = select_entries_and_count(entries_query, count_query, db_request_queue)
    if result is None:
        bot.delete_message(call.message.chat.id, call.message.id)
        bot_answer_with_error(bot, call.message, BOT_MSG[lang(call.message)]['db_answer_fail'])
        return
    entries_answer = result[0]
    count_answer = normalize_count_result(result[1])
    str_answer = prepare_user_history_str_message(call.message, entries_answer, count_answer, current_offset)

    menu = InlineKeyboardMarkup()
    go_front = InlineKeyboardButton('>>', callback_data=AdmMenuState.show_history + next_offset.__str__())
    go_back = InlineKeyboardButton('<<', callback_data=AdmMenuState.show_history + prev_offset.__str__())
    button_list = []
    if current_offset - prev_offset > 0:
        button_list.append(go_back)
    if count_answer - next_offset > 0:
        button_list.append(go_front)
    row_width = 2
    if len(button_list) == 1:
        row_width = 1
    button_delete_all_history = InlineKeyboardButton('Delete All History',
                                                     callback_data=AdmMenuState.accept_or_decline + 'history')
    if button_list:
        menu.add(*button_list, row_width=row_width)
    menu.add(button_delete_all_history)
    menu.add(make_back_button(AdmMenuState.back_to_main))

    retry(bot.edit_message_text)(str_answer, call.message.chat.id, call.message.id,
                                 disable_web_page_preview=True, parse_mode='HTML', reply_markup=menu)


@bot.callback_query_handler(is_admin=True, func=lambda c: c.data.startswith(AdmMenuState.edit_users))
def admin_menu_edit_users_menu(call: CallbackQuery):
    """Shows users as separated messages, incoming call.data can have a current offset and list of message_ids"""

    retry(bot.delete_message)(call.message.chat.id, call.message.id, max_attempt=2)
    current_offset, message_list = get_offset_and_id_list(call, prefix=AdmMenuState.edit_users)

    for message_id in message_list:
        retry(bot.delete_message)(call.message.chat.id, message_id, max_attempt=2)

    next_offset = current_offset + USER_PER_PAGE
    prev_offset = 0
    if current_offset:
        prev_offset = current_offset - USER_PER_PAGE

    entries_query = (
        select(TelegramUser.id, TelegramUser.user_name, TelegramUser.first_name, TelegramUser.last_name,
               UserPermissions.is_user, UserPermissions.is_admin)
        .outerjoin(UserPermissions).offset(current_offset).limit(USER_PER_PAGE)).order_by(TelegramUser.user_name)
    count_query = select(func.count('*')).select_from(TelegramUser).outerjoin(UserPermissions)
    result = select_entries_and_count(entries_query, count_query, db_request_queue)
    if result is None:
        retry(bot.delete_message)(call.message.chat.id, call.message.id)
        bot_answer_with_error(bot, call.message, BOT_MSG[lang(call.message)]['db_answer_fail'])
        return
    entries_answer = result[0]
    count_answer = normalize_count_result(result[1])
    message_list = []
    for entry in entries_answer:
        user_edit_menu = InlineKeyboardMarkup(row_width=2)
        user_edit_menu.add(*make_user_edit_buttons(entry[0], entry[5], entry[4]))
        try:
            message = retry(bot.send_message)(call.message.chat.id, f'<b>{entry[2]}</b>[{entry[0]}]',
                                              parse_mode='HTML', reply_markup=user_edit_menu, disable_notification=True)

        except Exception as e:
            log.exception('ex', e)
            message = call.message
        message_list.append(message.message_id.__str__())

    menu = InlineKeyboardMarkup()
    go_front = InlineKeyboardButton('>>', callback_data=AdmMenuState.edit_users +
                                                        f'{next_offset}-{"-".join(message_list)}')
    go_back = InlineKeyboardButton('<<', callback_data=AdmMenuState.edit_users +
                                                       f'{prev_offset}-{"-".join(message_list)}')
    button_list = []
    if current_offset - prev_offset > 0:
        button_list.append(go_back)
    if count_answer - next_offset > 0:
        button_list.append(go_front)
    row_width = 2
    if len(button_list) == 1:
        row_width = 1
    button_list.append(make_back_button(AdmMenuState.user_control + '-'.join(message_list)))
    menu.add(*button_list, row_width=row_width)
    retry(bot.send_message)(call.message.chat.id, f'Total users: {count_answer}', disable_web_page_preview=True,
                            parse_mode='HTML', reply_markup=menu, disable_notification=True)


@bot.message_handler(is_admin=True, commands=['admin'])
def admin_menu_first_show(message: Message):
    """Receive an /admin command, delete it and show the admin menu"""

    retry(bot.delete_message)(message.chat.id, message.id)
    menu = get_main_admin_menu()
    retry(bot.send_message)(message.chat.id, '<b>Welcome to Admin menu</b>', reply_markup=menu, parse_mode='HTML',
                            disable_notification=True)


@bot.message_handler(is_user=True, func=lambda m: m.content_type == 'text' and url(m.text))
def download_file_from_link(message: Message):
    """Central func of the bot, receive a link and convert it to mp3 file"""

    log.info(f'Input message from {message.from_user.username} id: {message.from_user.id} , text: {message.text}')
    dl_list = [message.text]
    # TODO: Make some checks of the incoming message
    bot_msg = bot.send_message(message.chat.id, BOT_MSG[lang(message)]["prepare_download"])

    downloading_hook = get_download_progress_hook(bot, bot_msg, msg_edit_queue)
    # Download file options, do not change tmpl without testing
    ydl_opts = {
        'format': 'bestaudio/best',
        'no_color': True,
        'outtmpl': {
            'default': '%(title)s.%(ext)s',
        },
        'progress_hooks': [downloading_hook],
        'logger': log,
    }
    # Send history to DB
    db_request_queue.put(
        DBMessage(command=DBCommand.AddNew, db_obj=BotHistory.new_from_message_obj(message), block=False))

    with MyYoutubeDL(params=ydl_opts) as ydl:
        try:
            info = retry(ydl.extract_info)(dl_list[0], gen_answer=True, bot_obj=bot, download=False,
                                           tg_message_obj=message,
                                           tg_error_msg=BOT_MSG[lang(message)]["error_getting_ydl_info"])
        except Exception as e:
            bot_answer_with_error(bot, message, str(e))
            log.exception(e)
            return

        file_name = os.path.join(MP3_DIR, file_name_manipulate(ydl.prepare_filename(info)))
        log.info(f"Title of downloaded file: {info.get('title')}")
        log_debug(info)
        # Prepare output filename
        ydl.params.update({'outtmpl': {'default': file_name}})

        # Calculate bitrate based on duration (Telegram has max transfer size 50 MB)
        video_duration: int = info.get('duration')
        bitrate_to_set = calculate_mp3_bitrate(video_duration)

        if bitrate_to_set == 0:
            retry(bot.delete_message)(bot_msg.chat.id, bot_msg.message_id)
            retry(bot.send_message)(message.chat.id, BOT_MSG[lang(message)]["file_too_long"])
            return

        # Install PP with right bitrate
        post_processor = ControlledPostProcessor(message=bot_msg, bot=bot,
                                                 user_lang_code=message.from_user.language_code, preferredcodec='mp3',
                                                 preferredquality=str(bitrate_to_set), msg_queue=msg_edit_queue)
        ydl.add_post_processor(post_processor)
        # Run process
        retry(ydl.download)(dl_list, gen_answer=True, bot_obj=bot, tg_message_obj=message,
                            tg_error_msg='Problem with downloading or postprocessing')
        # Delete inform message
        retry(bot.delete_message)(chat_id=message.chat.id, message_id=bot_msg.message_id)


@bot.message_handler(commands=['id'])
def get_id(message: Message):
    retry(bot.send_message)(message.chat.id, '{} {}'.format(BOT_MSG[lang(message)]['get_id'], message.from_user.id))


@bot.message_handler(is_user=False, commands=['start'])
def start_unauthorized(message: Message):
    retry(bot.send_message)(message.chat.id,
                            BOT_MSG[lang(message)]['start_unauth'].format(message.from_user.first_name))


@bot.message_handler(is_user=True, commands=['start'])
def start_authorized(message: Message):
    pass


@bot.message_handler(is_user=True)
def invalid_message(message: Message):
    bot.send_message(message.chat.id, BOT_MSG[lang(message)]['invalid_message'])


@bot.message_handler(func=lambda m: True)
def unauthorized(message: Message):
    bot.send_message(message.chat.id, BOT_MSG[lang(message)]['not_authorized'])
    log.warning(f'Unauthorized message from {message.from_user.username} id: {message.from_user.id}, '
                f'message{message.id}')


# Bot start messages
print(f'Elemental YouTube DL Tg Bot Version {BOT_VERSION}')
log.info(f'Starting Elemental YouTube DL Tg Bot Version {BOT_VERSION}')

# Bot Infinity polling
try:
    bot.infinity_polling()
except KeyboardInterrupt:
    pass
except Exception as e:
    log.exception(e)
finally:
    # Close threads when Interrupt
    db_request_queue.put(DBMessage(command=DBCommand.Quit))
    close_msg_edit_thread(msg_edit_queue)
    print('Quit')
