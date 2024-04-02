import ast
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from typing import List, Any

import requests
from sqlalchemy import desc
from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider

from configuration.config import TELEGRAM_BOT, USER_ID, WALLETS, API_KEY, OWNER_WALLET_ID
from database.objects import Payments, Session, Users

from requests.exceptions import ConnectionError as ConE, Timeout as Tm, ReadTimeout as RTm
from json.decoder import JSONDecodeError as JsonE

usdt_contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


@contextmanager
def create_session():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_wallet_by_id(user_id: int) -> str:
    with create_session() as session:
        from_wallet_id = session.query(Users.wallet_id).filter(Users.user_id == user_id).first()[0]
        return ast.literal_eval(WALLETS)[str(from_wallet_id)]["address"]


def get_balance(address, user_id) -> Any:
    try:
        req = requests.get("https://apilist.tronscan.org/api/account", params={"address": address}, timeout=5)
        address_info = json.loads(req.text)
        crypto_tokens = address_info["trc20token_balances"]
        trx_balance = int(address_info["balance"]) / 1_000_000
        usdt_balance = next((token["balance"] for token in crypto_tokens if
                             token["tokenAbbr"] == "USDT" and token["tokenId"] == usdt_contract), None)
        if usdt_balance is None:
            return 0, 0
        usdt_balance = int(usdt_balance) / 1_000_000
        return trx_balance, usdt_balance
    except KeyError as _:
        return None, None
    except (ConE, Tm, RTm, JsonE) as _:
        telegram_notify("🔍 Проблема с подключением к API Tronscan. Повторная попытка...", user_id)
        time.sleep(10)
        return get_balance(address, user_id)


def withdraw_balance(usdt_amount: float, send_to: str, send_from: str, priv_key: PrivateKey) -> None:
    client = Tron(HTTPProvider('https://api.trongrid.io/', api_key=API_KEY))
    contract = client.get_contract(usdt_contract)
    txn = (contract.functions.transfer(send_to, usdt_amount * 1_000_000)
           .with_owner(send_from)
           .fee_limit(50_000_000)
           .build()
           .sign(priv_key))
    txn.broadcast().wait()


def generate_user() -> None:
    with create_session() as session:
        user = session.query(Users).filter(Users.user_id == int(USER_ID)).first()
        if not user:
            session.add(Users(wallet_id=int(OWNER_WALLET_ID), user_id=int(USER_ID), action="unknown"))
        else:
            if user.wallet_id != int(OWNER_WALLET_ID):
                user.wallet_id = int(OWNER_WALLET_ID)


def get_action(user_id: int) -> str:
    with create_session() as session:
        return (
            session.query(Users.action)
            .filter(Users.user_id == int(user_id))
            .first()[0]
        )


def update_action(user_id: int, new_action: str) -> None:
    with create_session() as session:
        current_user = (
            session.query(Users).filter(Users.user_id == int(user_id)).first()
        )
        current_user.action = new_action


def parse_csv_file(file_in_io: BytesIO, user_id: int) -> str:
    try:
        from_wallet = get_wallet_by_id(user_id)
        buf = BytesIO(file_in_io.read())
        lines = buf.readlines()[1:]
        if len(lines) > 1:
            for line in lines:
                data = line.decode("utf-8").replace("\n", "").split(",")
                amount = float(data[1])
                add_payment(data[0], user_id)
                payment_timestamp = int(datetime.now().timestamp()) + 10
                update_payment(from_wallet, amount, payment_timestamp)
            return "✅ Все платежи успешно запланированы."
        raise Exception("Файл оказался пустым.")
    except Exception as exc:
        return f"⚠️ Произошла ошибка: {exc}"


def add_payment(wallet: str, user_id: int) -> None:
    with create_session() as session:
        session.add(Payments(wallet=wallet, from_wallet=get_wallet_by_id(user_id)))


def update_payment(
    from_wallet: str, amount: float = None, payment_timestamp: int = None, every_month: int = None
) -> None:
    with create_session() as session:
        last_payment = session.query(Payments).filter(Payments.from_wallet == from_wallet).order_by(desc(Payments.id)).first()
        if last_payment:
            if amount:
                last_payment.amount = amount
            if payment_timestamp:
                last_payment.payment_timestamp = payment_timestamp
            if every_month is not None:
                last_payment.every_month = every_month


def transactions(from_wallet: str) -> List[dict]:
    with create_session() as session:
        return [
            transaction.to_json()
            for transaction in session.query(Payments)
            .filter(Payments.status == 1, Payments.from_wallet == from_wallet)
            .all()
        ]


def delete_payment(payment_id: int, from_wallet: str) -> bool:
    with create_session() as session:
        payment = (
            session.query(Payments)
            .filter(Payments.id == payment_id, Payments.status == 1, from_wallet == from_wallet)
            .first()
        )
        if payment:
            session.delete(payment)
            return True
    return False


def check_awaiting_transactions() -> None:
    with create_session() as session:
        current_timestamp = int(datetime.now().timestamp())
        awaiting_transactions = [
            transaction.to_json()
            for transaction in session.query(Payments)
            .filter(
                Payments.payment_timestamp < current_timestamp, Payments.status == 1
            )
            .all()
        ]
        for transaction in awaiting_transactions:
            from_wallet = transaction["from_wallet"]
            wallet_id, secret = None, None
            for w_id in ast.literal_eval(WALLETS).keys():
                if from_wallet == ast.literal_eval(WALLETS)[str(w_id)]["address"]:
                    secret = ast.literal_eval(WALLETS)[str(w_id)]["private"]
                    wallet_id = int(w_id)
                    break
            amount = transaction["amount"]
            user_wallet = transaction["wallet"]
            every_month = transaction["every_month"]
            users = [user[0] for user in session.query(Users.user_id).filter(Users.wallet_id == wallet_id).all()]
            if wallet_id and secret:
                try:
                    tron, usdt = get_balance(from_wallet, 0)
                    if tron < 50:
                        for user_id in users:
                            telegram_notify("🔔 Не хватило $TRX монет для оплаты комиссий. Пополните TRON кошелёк, пожалуйста.", user_id)
                        continue
                    if usdt < amount:
                        for user_id in users:
                            telegram_notify("📞 Не хватило средств для выплаты перевода по запланированной заявке.", user_id)
                        continue
                    priv_key = PrivateKey(bytes.fromhex(secret))
                    withdraw_balance(amount, user_wallet, from_wallet, priv_key)
                    if every_month == 0:
                        transaction["status"] = 0
                    else:
                        now = datetime.now()
                        year = now.year
                        month = now.month + 1
                        day = now.day
                        transaction["payment_timestamp"] = int(
                            datetime(year, month, day).timestamp()
                        )
                    message = (
                        f"🚀 Была произведена запланированная выплата:\n\n"
                        f"👛 Кошелек: {user_wallet}\n"
                        f"💰 Сумма: {amount} USDT\n"
                        f"🌐 Сеть: TRC20 (Tron Network)\n"
                        f'{"🔄 Следующая выплата через месяц." if every_month else ""}'
                    )
                    for user_id in users:
                        telegram_notify(message, user_id)
                except Exception as exc:
                    for user_id in users:
                        telegram_notify(f"🆘 Произошла ошибка при выводе средств: {exc}", user_id)
        try:
            session.bulk_update_mappings(Payments, awaiting_transactions)
            time.sleep(15)
        except Exception as exc:
            print(f"🆘 Критическая ошибка: {exc}")
            sys.exit()


def telegram_notify(message: str, user_id: int):
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage?chat_id={user_id}&text={message}"
        )
        time.sleep(5)
    except Exception as _:
        pass
