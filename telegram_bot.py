import ast
import io
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot, Dispatcher, F, types
from sqlalchemy import desc

from configuration.config import TELEGRAM_BOT, WALLETS, USER_ID
from core import (
    add_payment,
    create_session,
    delete_payment,
    transactions,
    update_payment,
    update_action,
    get_action,
    get_balance, get_wallet_by_id, parse_csv_file,
)
from database.objects import Payments, Users

bot = Bot(token=TELEGRAM_BOT)
dp = Dispatcher()

check_wallets = "👛 Список ожидающихся переводов"
add_transfer = "🗒 Запланировать перевод"
add_transfers = "⏫ Массовая отправка переводов"
cancel_transfer = "🤖 Отменить перевод"
main_keyboard = [
    [types.KeyboardButton(text=add_transfer)],
    [types.KeyboardButton(text=add_transfers)],
    [types.KeyboardButton(text=cancel_transfer)],
    [types.KeyboardButton(text=check_wallets)],
]
main_keyboard = types.ReplyKeyboardMarkup(keyboard=main_keyboard)

menu = "📣 Вернуться в главное меню"
menu_keyboard = [[types.KeyboardButton(text=menu)]]
menu_keyboard = types.ReplyKeyboardMarkup(keyboard=menu_keyboard)

monthly_value = "📈 Перечислять ежемесячно."
one_time_value = "📉 Перечислить единоразово."
monthly_keyboard = [
    [types.KeyboardButton(text=monthly_value)],
    [types.KeyboardButton(text=one_time_value)],
]
monthly_keyboard = types.ReplyKeyboardMarkup(keyboard=monthly_keyboard)

access_error = "🚫 Произошла ошибка. Повторите попытку позже."
not_found = "🔢 Данное ID не найдено в запланированных транзакциях."
not_found_wallet = '🔄 Введите действительный $TRX кошелёк:'
inactive_wallet = "🔒 Данный кошелёк не активирован. Для активации переведите 1.3+ $TRX."
myself_wallet = "🫵 Невозможно настроить выплату на свой же кошелёк."

success_changes = "✅ Изменения успешно сохранены."
choose_action = "⚠️ Выберите действие:"
select_date = "📆 Выберите дату для отправки транзакции:"
monthly_payment = "🌛 Запланировать ежемесячный платёж:"
input_wallet = "🌚 Введите адрес кошелька получателя (Сеть: TRC20):"
send_file = "📩 Отправьте файл в формате .csv со столбцами адресов и суммой перевода."
usdt_to_send = "📁 Введите кол-во $USDT для перевода."
transaction_for_deletion = "🗑 Введите ID запланированной транзакции, которую нужно удалить:"

admin_user_actions = "💻 Работа с пользователями"
admin_add_user = "👨🏻‍💼✅ Добавить нового пользователя"
admin_delete_user = "👨🏻‍💼🚫 Удалить существующего пользователя."
admin_select_wallet = "👛 Доступ к какому кошельку открыть для пользователя:"
admin_already_added = "🔢 Пользователь с данным ID уже имеет доступ."
admin_user_not_found = "🔢 Пользователь с данным ID не имеет доступ."
admin_real_id = "🔢 Введите действительный ID пользователя в цифровом формате."
admin_action_with_user = "🔢 Вставьте ID пользователя, которого нужно"

admin_keyboard = [
    [types.KeyboardButton(text=add_transfer)],
    [types.KeyboardButton(text=add_transfers)],
    [types.KeyboardButton(text=cancel_transfer)],
    [types.KeyboardButton(text=check_wallets)],
    [types.KeyboardButton(text=admin_user_actions)],
]
admin_keyboard = types.ReplyKeyboardMarkup(keyboard=admin_keyboard)

admin_control_keyboard = [
    [types.KeyboardButton(text=admin_add_user)],
    [types.KeyboardButton(text=admin_delete_user)],
]
admin_control_keyboard = types.ReplyKeyboardMarkup(keyboard=admin_control_keyboard)


@dp.message(F.text)
async def real_dispatcher(message: types.Message) -> Any:
    sender_id = message.from_user.id
    with create_session() as session:
        wallet_id = session.query(Users.wallet_id).filter(Users.user_id == sender_id).first()
        if sender_id not in [user_id[0] for user_id in session.query(Users.user_id).all()] or wallet_id.wallet_id is None:
            return await message.answer(access_error)
        else:
            text = message.text
            if text == check_wallets:
                update_action(sender_id, "check_wallets")
            if text == add_transfer:
                update_action(sender_id, "add_transfer")
            if text == add_transfers:
                update_action(sender_id, "add_transfers")
            if text == cancel_transfer:
                update_action(sender_id, "cancel_transfer")
            if text == admin_user_actions:
                update_action(sender_id, "admin_user_actions")
            if text in [menu, "/start"]:
                return await return_to_menu(message)
            return await actions(message)


async def return_to_menu(message: types.Message) -> Any:
    sender_id = message.from_user.id
    with create_session() as session:
        from_wallet_id = session.query(Users.wallet_id).filter(Users.user_id == sender_id).first()[0]
        from_wallet = ast.literal_eval(WALLETS)[str(from_wallet_id)]["address"]
        last_transaction = session.query(Payments).filter(Payments.from_wallet == from_wallet).order_by(desc(Payments.id)).first()
        if last_transaction is not None:
            if (
                last_transaction.wallet is None
                or last_transaction.amount is None
                or last_transaction.payment_timestamp is None
            ):
                session.delete(last_transaction)
        update_action(sender_id, "unknown")
        if sender_id == int(USER_ID):
            last_user = session.query(Users).filter(Users.user_id != int(USER_ID)).order_by(desc(Users.id)).first()
            if last_user is not None:
                if last_user.wallet_id is None:
                    session.delete(last_user)
    if sender_id == int(USER_ID):
        return await message.answer(choose_action, reply_markup=admin_keyboard)
    return await message.answer(choose_action, reply_markup=main_keyboard)


async def actions(message: types.Message) -> Any:
    sender_id = message.from_user.id
    last_action = get_action(sender_id)
    text = message.text
    from_wallet = get_wallet_by_id(sender_id)

    if last_action == "check_wallets":
        payments_list = "⏰ Ожидаемые выплаты:"
        for transaction_info in transactions(from_wallet):
            date = datetime.fromtimestamp(
                int(transaction_info["payment_timestamp"])
            ).strftime("%Y-%m-%d")
            payments_list += f'\n\n💸 Выплата #{transaction_info["id"]}:\n'
            payments_list += f'{date} - {transaction_info["wallet"]} - {transaction_info["amount"]} USDT'
        return await message.answer(text=payments_list)

    if last_action == "cancel_transfer":
        update_action(sender_id, "selected_transfer")
        return await message.answer(transaction_for_deletion, reply_markup=menu_keyboard,)

    if last_action == "selected_transfer":
        try:
            transaction_id = int(message.text)
            deletion = delete_payment(transaction_id, from_wallet)
            if deletion:
                await message.answer(success_changes)
            else:
                raise Exception
        except Exception as _:
            await message.answer(not_found)
        finally:
            return await return_to_menu(message)

    if last_action == "add_transfer":
        with create_session() as session:
            last_transaction = (
                session.query(Payments).filter(Payments.from_wallet == from_wallet).order_by(desc(Payments.id)).first()
            )
            if last_transaction is not None:
                if (
                    last_transaction.wallet is None
                    or last_transaction.amount is None
                    or last_transaction.payment_timestamp is None
                ):
                    session.delete(last_transaction)
        update_action(sender_id, "selected_address")
        return await message.answer(input_wallet, reply_markup=menu_keyboard)

    if last_action == "selected_address":
        trx, usdt = get_balance(text, sender_id)
        if trx is None or usdt is None:
            return await message.answer(not_found_wallet, reply_markup=menu_keyboard,)
        if trx == 0:
            return await message.answer(inactive_wallet, reply_markup=menu_keyboard,)
        all_wallets = []
        for wallet in ast.literal_eval(WALLETS).keys():
            all_wallets.append(ast.literal_eval(WALLETS)[wallet]["address"])
        if text in all_wallets:
            return await message.answer(myself_wallet, reply_markup=menu_keyboard,)
        update_action(sender_id, "selected_amount")
        add_payment(text, sender_id)
        return await message.answer(usdt_to_send, reply_markup=menu_keyboard,)

    if last_action == "selected_amount":
        try:
            amount = int(message.text)
            if amount < 1:
                raise Exception
            update_payment(from_wallet=from_wallet, amount=amount)
            update_action(sender_id, "selected_payment_timestamp")
            date_keyboard = [
                [
                    types.KeyboardButton(
                        text=(datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
                    )
                ]
                for i in range(1, 31)
            ]
            date_keyboard = types.ReplyKeyboardMarkup(keyboard=date_keyboard)
            return await message.answer(select_date, reply_markup=date_keyboard)
        except Exception as _:
            return await message.answer(f'{usdt_to_send} Кол-во должно быть не меньше 1 USDT.', reply_markup=menu_keyboard,)

    if last_action == "selected_payment_timestamp":
        try:
            selected_date = datetime.strptime(text, "%Y-%m-%d").timestamp()
            update_payment(from_wallet=from_wallet, payment_timestamp=int(selected_date))
            update_action(sender_id, "selected_monthly_type")
            return await message.answer(monthly_payment, reply_markup=monthly_keyboard)
        except Exception as _:
            await message.answer(access_error)
            return await return_to_menu(message)

    if last_action == "selected_monthly_type":
        if text == monthly_value:
            update_payment(from_wallet=from_wallet, every_month=1)
        elif text == one_time_value:
            update_payment(from_wallet=from_wallet, every_month=0)
        else:
            return await message.answer(monthly_payment, reply_markup=monthly_keyboard)
        await message.answer(success_changes)

    if last_action == "add_transfers":
        update_action(sender_id, "send_csv_file")
        return await message.answer(send_file, reply_markup=menu_keyboard)

    if last_action == "send_csv_file":
        file_in_io = io.BytesIO()
        if message.content_type == 'document':
            await message.document.download(destination_file=file_in_io)
            result_msg = parse_csv_file(file_in_io, sender_id)
            await message.answer(result_msg)
        else:
            await message.answer("⚠️ Отправьте файл в формате .csv")

    if sender_id == int(USER_ID):
        if last_action == "admin_user_actions":
            update_action(sender_id, "choosen_admin_action")
            return await message.answer(choose_action, reply_markup=admin_control_keyboard, )
        if text == admin_add_user:
            update_action(sender_id, "admin_added_user")
            return await message.answer(f"{admin_action_with_user} добавить.", reply_markup=menu_keyboard,)
        if text == admin_delete_user:
            update_action(sender_id, "admin_deleted_user")
            return await message.answer(f"{admin_action_with_user} удалить.", reply_markup=menu_keyboard,)
        try:
            with create_session() as session:
                if last_action == "admin_added_user":
                    new_user_id = int(text)
                    check_user = session.query(Users).filter(Users.user_id == new_user_id).first()
                    if not check_user:
                        session.add(Users(user_id=new_user_id, action="unknown"))
                        update_action(sender_id, "wallet_chosen")
                        wallets_keyboard = [
                            [
                                types.KeyboardButton(
                                    text=ast.literal_eval(WALLETS)[str(wallet)]["address"]
                                )
                            ]
                            for wallet in ast.literal_eval(WALLETS).keys()
                        ]
                        wallets_keyboard = types.ReplyKeyboardMarkup(keyboard=wallets_keyboard)
                        return await message.answer(admin_select_wallet, reply_markup=wallets_keyboard)
                    else:
                        await message.answer(admin_already_added)
                        return await return_to_menu(message)
                if last_action == "wallet_chosen":
                    for wallet_id, wallet in ast.literal_eval(WALLETS).items():
                        if wallet["address"] == text:
                            last_user = session.query(Users).order_by(desc(Users.user_id)).first()
                            last_user.wallet_id = int(wallet_id)
                    await message.answer(success_changes)
                    return await return_to_menu(message)
                if last_action == "admin_deleted_user":
                    check_user = session.query(Users).filter(Users.user_id == int(text)).first()
                    if int(text) == int(USER_ID):
                        await message.answer(access_error)
                        return await return_to_menu(message)
                    if check_user:
                        session.delete(check_user)
                        await message.answer(success_changes)
                        return await return_to_menu(message)
                    await message.answer(admin_user_not_found)
                    return await return_to_menu(message)
        except ValueError:
            return await message.answer(admin_real_id, reply_markup=menu_keyboard,)

    return await return_to_menu(message)


async def start_bot():
    await dp.start_polling(bot)
