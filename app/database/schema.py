import datetime
from typing import Optional, List

import telebot.types
from sqlalchemy import ForeignKey, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TelegramUser(Base):
    __tablename__ = 'telegram_user'
    id: Mapped[int] = mapped_column(primary_key=True)
    is_bot: Mapped[bool] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_premium: Mapped[Optional[bool]] = mapped_column(nullable=True)
    history: Mapped[List["BotHistory"]] = relationship(back_populates='user')
    permissions: Mapped[Optional["UserPermissions"]] = relationship(back_populates='user')
    chat: Mapped["Chat"] = relationship(back_populates='user')

    @classmethod
    def map_from_message_obj(cls, message: telebot.types.Message):
        return TelegramUser(
            id=message.from_user.id,
            is_bot=message.from_user.is_bot,
            first_name=message.from_user.first_name,
            user_name=message.from_user.username,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code,
            is_premium=message.from_user.is_premium,
            chat=Chat.map_from_message_obj(message)
        )

    @staticmethod
    def list_from_message_obj(message: telebot.types.Message) -> List:
        return [
            {
                'id': message.from_user.id,
                'is_bot': message.from_user.is_bot,
                'first_name': message.from_user.first_name,
                'user_name': message.from_user.username,
                'last_name': message.from_user.last_name,
                'language_code': message.from_user.language_code,
                'is_premium': message.from_user.is_premium,
            }
        ]

    def __repr__(self) -> str:
        return f'TelegramUser(id: {self.id}, is_bot: {self.is_bot}, user_name: {self.user_name}, last_name: {self.last_name})'


class UserPermissions(Base):
    __tablename__ = 'user_permissions'
    user_id: Mapped[int] = mapped_column(ForeignKey('telegram_user.id'), primary_key=True)
    user: Mapped["TelegramUser"] = relationship(back_populates='permissions')
    is_admin: Mapped[bool] = mapped_column(nullable=None)
    is_user: Mapped[bool] = mapped_column(nullable=None)
    created_date: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    @staticmethod
    def get_update_data(id: int, is_admin: bool, is_user: bool):
        return [
            {
                'user_id': id,
                'is_admin': is_admin,
                'is_user': is_user
            }
        ]

    def __repr__(self) -> str:
        return f'UserPermissions(user_id: {self.user_id}, is_admin: {self.is_admin}, is_user: {self.is_user}, ' \
               f'adding_date: {self.created_date})'


class Chat(Base):
    __tablename__ = 'chat'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('telegram_user.id'))
    user: Mapped["TelegramUser"] = relationship(back_populates='chat')

    @classmethod
    def map_from_message_obj(cls, message: telebot.types.Message):
        return Chat(
            id=message.chat.id,
            user_id=message.from_user.id
        )

    def __repr__(self) -> str:
        return f'Chat(id: {self.id}, user_id: {self.user_id}'


class BotHistory(Base):
    __tablename__ = "bot_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement='auto')
    msg_text: Mapped[str] = mapped_column(nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey('telegram_user.id'))
    created_date: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    user: Mapped["TelegramUser"] = relationship(back_populates='history')

    @classmethod
    def new_from_message_obj(cls, message: telebot.types.Message):
        return BotHistory(
            msg_text=message.text,
            user_id=message.from_user.id
        )
