import asyncio
import logging
import sqlite3
import sys
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ---------------- CONFIGURATION ----------------
BOT_TOKEN = "8952721816:AAFoHyj192PVibTW9tiFHVsdCU8lVRP0qpc"
CODER_ID = 15407194066  # Ваш Telegram ID (Режим бога)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------- DATABASE SETUP ----------------
conn = sqlite3.connect("bot_database.db")
cursor = conn.cursor()

# Таблица пользователей и ролей: coder, owner, helper, user
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'user'
)
"""
)

# Таблица заявок / жалоб
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    status TEXT DEFAULT 'pending'
)
"""
)
conn.commit()

# Гарантируем, что Кодер имеет нужные права в БД
cursor.execute(
    "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, 'coder')",
    (CODER_ID,),
)
conn.commit()


def get_user_role(user_id: int) -> str:
    if user_id == CODER_ID:
        return "coder"
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else "user"


def set_user_role(user_id: int, role: str):
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
        (user_id, role),
    )
    conn.commit()


# ---------------- STATES (FSM) ----------------
class TicketState(StatesGroup):
    waiting_for_ticket = State()


class AdminState(StatesGroup):
    waiting_for_add_helper = State()
    waiting_for_remove_helper = State()
    waiting_for_add_owner = State()
    waiting_for_remove_owner = State()


# ---------------- USER HANDLERS ----------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    welcome_text = (
        "Здравствуйте, уважаемый пользователь бота Project Forum Kursk!\n\n"
        "Отправьте нам вашу жалобу, и наша команда в ближайшее время ее рассмотрит.\n\n"
        "<b>Желательная форма подачи:</b>\n"
        "Ваш ник нейм\n"
        "Ник нейм нарушителя\n"
        "Ваш сервер\n\n"
        "Спасибо, что пользуетесь нашими услугами.\n"
        "С уважением, Kursk Project!"
    )
    await message.answer(welcome_text, parse_mode="HTML")
    await message.answer(
        "Напишите текст вашей жалобы/заявки следующим сообщением:"
    )
    await state.set_state(TicketState.waiting_for_ticket)


@dp.message(TicketState.waiting_for_ticket)
async def process_ticket(message: types.Message, state: FSMContext):
    ticket_text = message.text
    user_id = message.from_user.id

    cursor.execute(
        "INSERT INTO tickets (user_id, text) VALUES (?, ?)",
        (user_id, ticket_text),
    )
    conn.commit()
    ticket_id = cursor.lastrowid

    await state.clear()
    await message.answer(
        f"Ваша заявка #{ticket_id} успешно отправлена и зарегистрирована! Ожидайте ответа."
    )


# ---------------- HELPER & ADMIN COMMANDS ----------------
@dp.message(Command("help"))
async def cmd_help_menu(message: types.Message):
    role = get_user_role(message.from_user.id)
    if role not in ["helper", "owner", "coder"]:
        await message.answer("У вас нет доступа к командам хелпера.")
        return

    text = (
        "<b>📌 Панель Хелпера</b>\n\n"
        "Доступные действия:\n"
        "• Просмотр и принятие активных заявок\n"
        "• Удаление заявок\n\n"
        "Используйте кнопку ниже для перехода в список заявок."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Просмотреть заявки", callback_data="list_tickets"
                )
            ]
        ]
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("admin"))
async def cmd_admin_menu(message: types.Message):
    role = get_user_role(message.from_user.id)
    if role not in ["owner", "coder"]:
        await message.answer("У вас нет доступа к админ-панели.")
        return

    text = f"<b>⚙️ Главная Админ-Панель</b>\nВаш ранг: <b>{role.upper()}</b>\n\n Выберите нужное действие:"

    buttons = [
        [
            InlineKeyboardButton(
                text="📥 Управление заявками", callback_data="list_tickets"
            )
        ],
        [
            InlineKeyboardButton(
                text="➕ Назначить Хелпера", callback_data="add_helper"
            ),
            InlineKeyboardButton(
                text="➖ Снять Хелпера", callback_data="remove_helper"
            ),
        ],
    ]

    if role == "coder":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="👑 Назначить Основателя", callback_data="add_owner"
                ),
                InlineKeyboardButton(
                    text="❌ Снять Основателя", callback_data="remove_owner"
                ),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🚨 Очистить базу заявок (БОГ)",
                    callback_data="clear_tickets",
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ---------------- CALLBACK HANDLERS (ADMIN & HELPER) ----------------
@dp.callback_query(F.data == "list_tickets")
async def process_list_tickets(callback: types.CallbackQuery):
    role = get_user_role(callback.from_user.id)
    if role not in ["helper", "owner", "coder"]:
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    cursor.execute(
        "SELECT id, user_id, text FROM tickets WHERE status = 'pending' LIMIT 10"
    )
    tickets = cursor.fetchall()

    if not tickets:
        await callback.message.edit_text(" На данный момент нет открытых заявок.")
        return

    await callback.message.edit_text("📋 <b>Список активных заявок:</b>", parse_mode="HTML")
    for t_id, u_id, t_text in tickets:
        ticket_info = (
            f"<b>Заявка #{t_id}</b>\nОт пользователя ID: <code>{u_id}</code>\n\n"
            f"<b>Текст:</b>\n{t_text}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Принять", callback_data=f"accept_{t_id}"
                    ),
                    InlineKeyboardButton(
                        text="🗑 Удалить", callback_data=f"delete_{t_id}"
                    ),
                ]
            ]
        )
        await callback.message.answer(
            ticket_info, parse_mode="HTML", reply_markup=kb
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("accept_"))
async def process_accept_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split("_")[1])
    cursor.execute(
        "SELECT user_id FROM tickets WHERE id = ?", (ticket_id,)
    )
    row = cursor.fetchone()

    if row:
        user_id = row[0]
        cursor.execute(
            "UPDATE tickets SET status = 'accepted' WHERE id = ?", (ticket_id,)
        )
        conn.commit()

        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"✅ Ваша заявка #{ticket_id} была принята и обработана администратором!",
            )
        except Exception:
            pass

        await callback.message.edit_text(
            f"✅ Заявка #{ticket_id} успешно **ПРИНЯТА**."
        )
    else:
        await callback.message.edit_text("Заявка не найдена.")


@dp.callback_query(F.data.startswith("delete_"))
async def process_delete_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split("_")[1])
    cursor.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    conn.commit()

    await callback.message.edit_text(f"🗑 Заявка #{ticket_id} **УДАЛЕНА**.")


# ---------------- ROLE MANAGEMENT HANDLERS ----------------
@dp.callback_query(F.data == "add_helper")
async def add_helper_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите Telegram ID пользователя для назначения Хелпером:")
    await state.set_state(AdminState.waiting_for_add_helper)
    await callback.answer()


@dp.message(AdminState.waiting_for_add_helper)
async def add_helper_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите числовой Telegram ID.")
        return
    target_id = int(message.text)
    set_user_role(target_id, "helper")
    await state.clear()
    await message.answer(f" Пользователь <code>{target_id}</code> успешно назначен **Хелпером**!", parse_mode="HTML")


@dp.callback_query(F.data == "remove_helper")
async def remove_helper_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите Telegram ID пользователя для снятия ролей:")
    await state.set_state(AdminState.waiting_for_remove_helper)
    await callback.answer()


@dp.message(AdminState.waiting_for_remove_helper)
async def remove_helper_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите числовой Telegram ID.")
        return
    target_id = int(message.text)
    if target_id == CODER_ID:
        await message.answer("Нельзя снять роль с Кодера!")
        return
    set_user_role(target_id, "user")
    await state.clear()
    await message.answer(f" Роли с пользователя <code>{target_id}</code> сняты.", parse_mode="HTML")


@dp.callback_query(F.data == "add_owner")
async def add_owner_start(callback: types.CallbackQuery, state: FSMContext):
    if get_user_role(callback.from_user.id) != "coder":
        await callback.answer("Только Кодер может назначать Основателей!", show_alert=True)
        return
    await callback.message.answer("Введите Telegram ID для назначения Основателем:")
    await state.set_state(AdminState.waiting_for_add_owner)
    await callback.answer()


@dp.message(AdminState.waiting_for_add_owner)
async def add_owner_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите числовой Telegram ID.")
        return
    target_id = int(message.text)
    set_user_role(target_id, "owner")
    await state.clear()
    await message.answer(f"👑 Пользователь <code>{target_id}</code> назначен **Основателем**!", parse_mode="HTML")


@dp.callback_query(F.data == "remove_owner")
async def remove_owner_start(callback: types.CallbackQuery, state: FSMContext):
    if get_user_role(callback.from_user.id) != "coder":
        await callback.answer("Только Кодер может снимать Основателей!", show_alert=True)
        return
    await callback.message.answer("Введите Telegram ID Основателя для снятия прав:")
    await state.set_state(AdminState.waiting_for_remove_owner)
    await callback.answer()


@dp.message(AdminState.waiting_for_remove_owner)
async def remove_owner_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите числовой Telegram ID.")
        return
    target_id = int(message.text)
    if target_id == CODER_ID:
        await message.answer("Кодера нельзя разжаловать!")
        return
    set_user_role(target_id, "user")
    await state.clear()
    await message.answer(f" Роль Основателя с <code>{target_id}</code> успешно снята.", parse_mode="HTML")


@dp.callback_query(F.data == "clear_tickets")
async def clear_tickets_godmode(callback: types.CallbackQuery):
    if get_user_role(callback.from_user.id) != "coder":
        await callback.answer("Функция доступна только для Кодера!", show_alert=True)
        return
    cursor.execute("DELETE FROM tickets")
    conn.commit()
    await callback.message.answer("🔥 Все заявки были безвозвратно очищены (Режим Бога).")
    await callback.answer()


# ---------------- MAIN START ----------------
async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Бот успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
