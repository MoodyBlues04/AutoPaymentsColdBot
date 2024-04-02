import asyncio
import sys
import time
from threading import Thread

from core import check_awaiting_transactions, generate_user, create_session
from database.objects import Base, engine, Payments
from telegram_bot import start_bot


def main_iterator() -> None:
    while True:
        check_awaiting_transactions()
        time.sleep(60)


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    generate_user()

    iterator = Thread(target=main_iterator)
    iterator.daemon = True
    iterator.start()

    asyncio.run(start_bot())

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        sys.exit()
