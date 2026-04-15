"""
Telegram-бот для записи клиентов на приём.

Стек: Python 3.11, aiogram 3, SQLite
Автор: JARVIS (Claude Code)

Функционал:
- Запись на приём (выбор даты → времени → подтверждение)
- Просмотр и отмена своих записей
- Уведомление админу о новых записях и отменах
- Автоматическое напоминание за 1 час до приёма
"""

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db,
    save_user,
    get_available_dates,
    get_available_slots,
    create_appointment,
    get_user_appointments,
    cancel_appointment,
    get_appointments_to_remind,
    mark_reminded,
    get_appointments_for_date,
    DAY_NAMES,
)

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Инициализация ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


# =============================================
#  Главное меню (ReplyKeyboard — всегда внизу)
# =============================================
def main_menu() -> ReplyKeyboardMarkup:
    """Клавиатура главного меню — всегда видна пользователю."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="❌ Отменить запись")],
        ],
        resize_keyboard=True,
    )


# =============================================
#  /start — приветствие
# =============================================
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие + сохранение пользователя + главное меню."""
    user = message.from_user
    save_user(user.id, user.full_name, user.username)

    await message.answer(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу тебе записаться на занятие.\n"
        "Выбери действие в меню ниже:",
        reply_markup=main_menu(),
    )

    # Уведомить админа о новом пользователе
    if ADMIN_ID:
        username = f"@{user.username}" if user.username else "—"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"👤 <b>Новый пользователь</b>\n"
                f"Имя: {user.full_name}\n"
                f"TG: {username}",
            )
        except Exception:
            pass


# =============================================
#  📅 Записаться — шаг 1: выбор даты
# =============================================
@router.message(F.text == "📅 Записаться")
async def book_step1_date(message: Message):
    """Показываем ближайшие 7 рабочих дней."""
    dates = get_available_dates()

    # Inline-кнопки с датами
    buttons = []
    for d in dates:
        slots = get_available_slots(d["date"])
        count = len(slots)
        label = f"{d['label']}  ({count} {'мест' if count != 1 else 'место'})"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"date:{d['date']}")]
        )

    await message.answer(
        "📅 <b>Выбери дату:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  📅 Записаться — шаг 2: выбор времени
# =============================================
@router.callback_query(F.data.startswith("date:"))
async def book_step2_time(callback: CallbackQuery):
    """Показываем свободные слоты на выбранную дату."""
    await callback.answer()
    date_str = callback.data.split(":")[1]

    slots = get_available_slots(date_str)

    if not slots:
        await callback.message.edit_text(
            "😔 К сожалению, на этот день всё занято.\n"
            "Попробуй другую дату — нажми «📅 Записаться»."
        )
        return

    # Кнопки со свободными слотами (по 3 в ряд)
    buttons = []
    row = []
    for slot in slots:
        row.append(
            InlineKeyboardButton(text=slot, callback_data=f"time:{date_str}:{slot}")
        )
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Кнопка "Назад"
    buttons.append(
        [InlineKeyboardButton(text="◀️ Назад к датам", callback_data="back_to_dates")]
    )

    # Красивая дата
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

    await callback.message.edit_text(
        f"🕐 <b>Свободные слоты на {day_label}:</b>\n\nВыбери время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  📅 Записаться — шаг 3: подтверждение
# =============================================
@router.callback_query(F.data.startswith("time:"))
async def book_step3_confirm(callback: CallbackQuery):
    """Создаём запись и уведомляем всех."""
    await callback.answer()
    _, date_str, time_str = callback.data.split(":")
    user = callback.from_user

    # Проверяем, что слот ещё свободен
    available = get_available_slots(date_str)
    if time_str not in available:
        await callback.message.edit_text(
            "😔 Упс, этот слот только что заняли!\n"
            "Попробуй выбрать другое время — «📅 Записаться»."
        )
        return

    # Создаём запись
    appt_id = create_appointment(user.id, date_str, time_str)

    # Красивая дата
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m.%Y')}"

    await callback.message.edit_text(
        f"✅ <b>Ты записан(а)!</b>\n\n"
        f"📅 Дата: {day_label}\n"
        f"🕐 Время: {time_str}\n\n"
        f"Я напомню за 1 час до приёма.\n"
        f"Ждём тебя! 🎤"
    )

    # Уведомление админу
    if ADMIN_ID:
        username = f"@{user.username}" if user.username else "—"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📌 <b>Новая запись!</b>\n\n"
                f"Клиент: {user.full_name}\n"
                f"TG: {username}\n"
                f"Дата: {day_label}\n"
                f"Время: {time_str}\n"
                f"ID записи: #{appt_id}",
            )
        except Exception:
            pass


# =============================================
#  Кнопка "Назад к датам"
# =============================================
@router.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery):
    """Возврат к списку дат."""
    await callback.answer()
    dates = get_available_dates()

    buttons = []
    for d in dates:
        slots = get_available_slots(d["date"])
        count = len(slots)
        label = f"{d['label']}  ({count} {'мест' if count != 1 else 'место'})"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"date:{d['date']}")]
        )

    await callback.message.edit_text(
        "📅 <b>Выбери дату:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  📋 Мои записи
# =============================================
@router.message(F.text == "📋 Мои записи")
async def my_appointments(message: Message):
    """Показать активные записи пользователя."""
    appointments = get_user_appointments(message.from_user.id)

    if not appointments:
        await message.answer(
            "📋 У тебя пока нет записей.\n\n"
            "Нажми «📅 Записаться», чтобы выбрать время!"
        )
        return

    lines = ["📋 <b>Твои записи:</b>\n"]
    for a in appointments:
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"
        lines.append(f"  • {day_label} в {a['time']}")

    await message.answer("\n".join(lines))


# =============================================
#  ❌ Отменить запись
# =============================================
@router.message(F.text == "❌ Отменить запись")
async def cancel_menu(message: Message):
    """Показать записи с кнопками отмены."""
    appointments = get_user_appointments(message.from_user.id)

    if not appointments:
        await message.answer("У тебя нет активных записей.")
        return

    buttons = []
    for a in appointments:
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ {day_label} в {a['time']}",
                callback_data=f"cancel:{a['id']}",
            )
        ])

    await message.answer(
        "Какую запись отменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_confirm(callback: CallbackQuery):
    """Отмена записи + уведомление админу."""
    await callback.answer()
    appt_id = int(callback.data.split(":")[1])

    appt = cancel_appointment(appt_id)
    if not appt:
        await callback.message.edit_text("Запись не найдена.")
        return

    date_obj = datetime.strptime(appt["date"], "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

    await callback.message.edit_text(
        f"✅ Запись на {day_label} в {appt['time']} отменена.\n\n"
        f"Если передумаешь — жми «📅 Записаться»!"
    )

    # Уведомление админу
    if ADMIN_ID:
        user = callback.from_user
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❌ <b>Отмена записи</b>\n\n"
                f"Клиент: {user.full_name}\n"
                f"Дата: {day_label}\n"
                f"Время: {appt['time']}",
            )
        except Exception:
            pass


# =============================================
#  Напоминания (запускается по расписанию)
# =============================================
async def send_reminders():
    """Отправить напоминание за 1 час до приёма."""
    appointments = get_appointments_to_remind()

    for a in appointments:
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

        try:
            await bot.send_message(
                a["user_id"],
                f"⏰ <b>Напоминание!</b>\n\n"
                f"Через час у тебя занятие:\n"
                f"📅 {day_label} в {a['time']}\n\n"
                f"Ждём тебя! 🎤",
            )
            mark_reminded(a["id"])
            logger.info(f"Reminder sent to {a['user_id']} for {a['date']} {a['time']}")
        except Exception as e:
            logger.error(f"Reminder error for {a['user_id']}: {e}")


# =============================================
#  Любой другой текст
# =============================================
@router.message(F.text)
async def fallback(message: Message):
    """Ответ на любые сообщения, не попавшие в хендлеры."""
    await message.answer(
        "Используй меню ниже для навигации 👇\n\n"
        "📅 Записаться\n"
        "📋 Мои записи\n"
        "❌ Отменить запись",
        reply_markup=main_menu(),
    )


# =============================================
#  Запуск бота
# =============================================
async def main():
    # Инициализация базы данных
    init_db()
    logger.info("Database initialized")

    # Планировщик напоминаний — каждые 5 минут
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", minutes=5)
    scheduler.start()
    logger.info("Reminder scheduler started")

    # Запуск бота
    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
