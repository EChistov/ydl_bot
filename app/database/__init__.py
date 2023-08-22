import sys

from sqlalchemy import create_engine
from database.schema import Base
from telebot import logger as log

try:
    db_engine = create_engine('sqlite:///database.db')
except Exception as e:
    log.exception(e)
    sys.exit(-1)
else:
    Base.metadata.create_all(db_engine)
