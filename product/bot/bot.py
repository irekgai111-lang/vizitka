"""
Telegram-бот для записи на маникюр/педикюр.

Стек: Python 3.11+, aiogram 3, SQLite
Клиент выбирает: услугу → дату → время → готово!
Мастер получает уведомления. Клиент получает напоминание за 1 час.
"""

import asyncio
import logging
from datetime import datetime
from urllib.parse import quote

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
    save_phone,
    get_available_dates,
    get_available_slots,
    create_appointment,
    get_user_appointments,
    cancel_appointment,
    get_appointments_to_remind,
    mark_reminded,
    get_appointments_for_date,
    SERVICES,
    DAY_NAMES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Хранилище выбора пользователя (в памяти, не в БД)
user_state: dict[int, dict] = {}


def google_calendar_url(title: str, date_str: str, time_str: str, duration_min: int, description: str = "") -> str:
    """Генерирует ссылку для добавления события в Google Календарь."""
    start_h, start_m = map(int, time_str.split(":"))
    end_total = start_h * 60 + start_m + duration_min
    end_h, end_m = end_total // 60, end_total % 60
    date_clean = date_str.replace("-", "")
    start_dt = f"{date_clean}T{start_h:02d}{start_m:02d}00"
    end_dt = f"{date_clean}T{end_h:02d}{end_m:02d}00"
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(title)}"
        f"&dates={start_dt}/{end_dt}"
        f"&ctz=Europe/Moscow"
        f"&details={quote(description)}"
    )


# =============================================
#  Главное меню
# =============================================
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💅 Записаться")],
            [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="❌ Отменить запись")],
            [KeyboardButton(text="💰 Цены"), KeyboardButton(text="📍 О мастере")],
        ],
        resize_keyboard=True,
    )


# =============================================
#  /start
# =============================================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    save_user(user.id, user.full_name, user.username)

    await message.answer(
        f"Привет, {user.first_name}! 💅\n\n"
        "Я — помощник для записи на маникюр.\n"
        "Запишу тебя быстро и без звонков!\n\n"
        "Выбери действие в меню:",
        reply_markup=main_menu(),
    )

    # Уведомить мастера
    if ADMIN_ID:
        username = f"@{user.username}" if user.username else "—"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"👤 <b>Новый клиент!</b>\n"
                f"Имя: {user.full_name}\n"
                f"TG: {username}",
            )
        except Exception:
            pass


# =============================================
#  💰 Цены
# =============================================
@router.message(F.text == "💰 Цены")
async def cmd_prices(message: Message):
    lines = ["<b>💰 Наши услуги и цены:</b>\n"]
    for key, s in SERVICES.items():
        hours = s["duration"] // 60
        mins = s["duration"] % 60
        dur_str = f"{hours}ч" if not mins else f"{hours}ч {mins}мин" if hours else f"{mins} мин"
        lines.append(f"{s['emoji']} <b>{s['name']}</b> — {s['price']} руб. ({dur_str})")

    lines.append("\nЗаписаться — жми «💅 Записаться»!")
    await message.answer("\n".join(lines))


# =============================================
#  📍 О мастере
# =============================================
@router.message(F.text == "📍 О мастере")
async def cmd_about(message: Message):
    await message.answer(
        "<b>📍 О мастере</b>\n\n"
        "Сертифицированный мастер маникюра и педикюра.\n"
        "Опыт работы — более 5 лет.\n"
        "Стерильные инструменты, премиум-материалы.\n\n"
        "🕐 Режим работы: Пн-Сб, 09:00–20:00\n"
        "📍 Адрес: Рамус Молл, 5 этаж\n\n"
        "Записаться — «💅 Записаться»"
    )


# =============================================
#  💅 Записаться — шаг 1: выбор услуги
# =============================================
@router.message(F.text == "💅 Записаться")
async def book_step1_service(message: Message):
    buttons = []
    for key, s in SERVICES.items():
        label = f"{s['emoji']} {s['name']} — {s['price']}₽"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"svc:{key}")])

    await message.answer(
        "<b>Выбери услугу:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  Шаг 2: выбор даты
# =============================================
@router.callback_query(F.data.startswith("svc:"))
async def book_step2_date(callback: CallbackQuery):
    await callback.answer()
    service_key = callback.data.split(":")[1]
    service = SERVICES[service_key]

    # Сохраняем выбор пользователя
    user_state[callback.from_user.id] = {"service": service_key}

    dates = get_available_dates()
    buttons = []
    for d in dates:
        slots = get_available_slots(d["date"], service["duration"])
        count = len(slots)
        if count == 0:
            label = f"{d['label']}  — нет мест"
        else:
            label = f"{d['label']}  ({count} {'мест' if count != 1 else 'место'})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"date:{d['date']}")])

    await callback.message.edit_text(
        f"Услуга: <b>{service['emoji']} {service['name']}</b>\n\n"
        f"📅 Выбери дату:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  Шаг 3: выбор времени
# =============================================
@router.callback_query(F.data.startswith("date:"))
async def book_step3_time(callback: CallbackQuery):
    await callback.answer()
    date_str = callback.data.split(":")[1]

    uid = callback.from_user.id
    state = user_state.get(uid, {})
    service_key = state.get("service")
    if not service_key:
        await callback.message.edit_text("Что-то пошло не так. Нажми «💅 Записаться» заново.")
        return

    service = SERVICES[service_key]
    state["date"] = date_str

    slots = get_available_slots(date_str, service["duration"])

    if not slots:
        await callback.message.edit_text(
            "😔 На этот день свободных мест нет.\n"
            "Нажми «💅 Записаться» и выбери другой день."
        )
        return

    # Кнопки со слотами (по 3 в ряд)
    buttons = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"time:{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"svc:{service_key}")])

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

    hours = service["duration"] // 60
    mins = service["duration"] % 60
    dur_str = f"{hours}ч" if not mins else f"{hours}ч {mins}мин" if hours else f"{mins} мин"

    await callback.message.edit_text(
        f"Услуга: <b>{service['emoji']} {service['name']}</b> ({dur_str})\n"
        f"Дата: <b>{day_label}</b>\n\n"
        f"🕐 Выбери время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =============================================
#  Шаг 4: подтверждение записи
# =============================================
@router.callback_query(F.data.startswith("time:"))
async def book_step4_confirm(callback: CallbackQuery):
    await callback.answer()
    time_str = callback.data.split(":")[1] + ":" + callback.data.split(":")[2]

    uid = callback.from_user.id
    state = user_state.get(uid, {})
    service_key = state.get("service")
    date_str = state.get("date")

    if not service_key or not date_str:
        await callback.message.edit_text("Что-то пошло не так. Нажми «💅 Записаться» заново.")
        return

    service = SERVICES[service_key]

    # Проверяем, что слот ещё свободен
    available = get_available_slots(date_str, service["duration"])
    if time_str not in available:
        await callback.message.edit_text(
            "😔 Ой, это время только что заняли!\n"
            "Нажми «💅 Записаться» и выбери другое."
        )
        return

    # Создаём запись
    appt_id = create_appointment(uid, date_str, time_str, service_key, service["duration"])

    # Считаем время окончания
    start_h, start_m = map(int, time_str.split(":"))
    end_total = start_h * 60 + start_m + service["duration"]
    end_str = f"{end_total // 60:02d}:{end_total % 60:02d}"

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m.%Y')}"

    # Ссылка на Google Календарь для клиента
    client_cal_url = google_calendar_url(
        title=f"{service['name']}",
        date_str=date_str,
        time_str=time_str,
        duration_min=service["duration"],
        description=f"Запись через бот. {service['price']} руб.",
    )
    client_cal_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Добавить в календарь", url=client_cal_url)]
    ])

    await callback.message.edit_text(
        f"✅ <b>Ты записана!</b>\n\n"
        f"{service['emoji']} {service['name']}\n"
        f"📅 {day_label}\n"
        f"🕐 {time_str} — {end_str}\n"
        f"💰 {service['price']} руб.\n\n"
        f"Напомню за 1 час до визита!\n"
        f"Ждём тебя! 💅✨",
        reply_markup=client_cal_btn,
    )

    # Уведомить мастера
    if ADMIN_ID:
        user = callback.from_user
        username = f"@{user.username}" if user.username else "—"

        # Ссылка на Google Календарь для мастера
        admin_cal_url = google_calendar_url(
            title=f"{service['name']} — {user.full_name}",
            date_str=date_str,
            time_str=time_str,
            duration_min=service["duration"],
            description=f"Клиент: {user.full_name}\nTG: {username}\nСумма: {service['price']} руб.",
        )
        admin_cal_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Добавить в календарь", url=admin_cal_url)]
        ])

        try:
            await bot.send_message(
                ADMIN_ID,
                f"📌 <b>Новая запись!</b>\n\n"
                f"Клиент: {user.full_name}\n"
                f"TG: {username}\n"
                f"Услуга: {service['emoji']} {service['name']}\n"
                f"Дата: {day_label}\n"
                f"Время: {time_str} — {end_str}\n"
                f"Сумма: {service['price']} руб.",
                reply_markup=admin_cal_btn,
            )
        except Exception:
            pass

    # Очистить состояние
    user_state.pop(uid, None)


# =============================================
#  📋 Мои записи
# =============================================
@router.message(F.text == "📋 Мои записи")
async def my_appointments(message: Message):
    appointments = get_user_appointments(message.from_user.id)

    if not appointments:
        await message.answer(
            "📋 У тебя пока нет записей.\n\n"
            "Жми «💅 Записаться»!"
        )
        return

    lines = ["<b>📋 Твои записи:</b>\n"]
    for a in appointments:
        service = SERVICES.get(a["service_key"], {})
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"
        svc_name = service.get("name", a["service_key"])
        emoji = service.get("emoji", "")
        lines.append(f"  • {day_label} в {a['time']} — {emoji} {svc_name}")

    await message.answer("\n".join(lines))


# =============================================
#  ❌ Отменить запись
# =============================================
@router.message(F.text == "❌ Отменить запись")
async def cancel_menu(message: Message):
    appointments = get_user_appointments(message.from_user.id)

    if not appointments:
        await message.answer("У тебя нет активных записей.")
        return

    buttons = []
    for a in appointments:
        service = SERVICES.get(a["service_key"], {})
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"
        svc_name = service.get("name", "")
        buttons.append([InlineKeyboardButton(
            text=f"❌ {day_label} {a['time']} — {svc_name}",
            callback_data=f"cancel:{a['id']}",
        )])

    await message.answer(
        "Какую запись отменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_confirm(callback: CallbackQuery):
    await callback.answer()
    appt_id = int(callback.data.split(":")[1])

    appt = cancel_appointment(appt_id)
    if not appt:
        await callback.message.edit_text("Запись не найдена.")
        return

    service = SERVICES.get(appt["service_key"], {})
    date_obj = datetime.strptime(appt["date"], "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

    await callback.message.edit_text(
        f"✅ Запись отменена:\n"
        f"{day_label} в {appt['time']} — {service.get('name', '')}\n\n"
        f"Если передумаешь — «💅 Записаться»!"
    )

    # Уведомить мастера
    if ADMIN_ID:
        user = callback.from_user
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❌ <b>Отмена записи</b>\n\n"
                f"Клиент: {user.full_name}\n"
                f"Услуга: {service.get('name', '')}\n"
                f"Дата: {day_label}\n"
                f"Время: {appt['time']}",
            )
        except Exception:
            pass


# =============================================
#  Напоминания
# =============================================
async def send_reminders():
    appointments = get_appointments_to_remind()
    for a in appointments:
        service = SERVICES.get(a["service_key"], {})
        date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
        day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

        try:
            await bot.send_message(
                a["user_id"],
                f"⏰ <b>Напоминание!</b>\n\n"
                f"Через час у тебя:\n"
                f"{service.get('emoji', '')} {service.get('name', '')}\n"
                f"📅 {day_label} в {a['time']}\n\n"
                f"Ждём тебя! 💅",
            )
            mark_reminded(a["id"])
        except Exception as e:
            logger.error(f"Reminder error: {e}")


# =============================================
#  /admin — расписание на день (только для мастера)
# =============================================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return

    # Можно указать дату: /admin 2026-04-16, иначе — сегодня
    args = message.text.split()
    today = datetime.now().strftime("%Y-%m-%d")
    date_str = args[1] if len(args) > 1 else today

    appointments = get_appointments_for_date(date_str)

    if not appointments:
        await message.answer(f"На {date_str} записей нет.")
        return

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_label = f"{DAY_NAMES[date_obj.weekday()]} {date_obj.strftime('%d.%m')}"

    lines = [f"<b>📋 Записи на {day_label}:</b>\n"]
    total = 0
    for a in appointments:
        service = SERVICES.get(a["service_key"], {})
        start_h, start_m = map(int, a["time"].split(":"))
        end_total = start_h * 60 + start_m + a["duration"]
        end_str = f"{end_total // 60:02d}:{end_total % 60:02d}"
        phone = a.get("phone") or "—"
        username = f"@{a['username']}" if a.get("username") else "—"
        price = service.get("price", 0)
        total += price

        lines.append(
            f"🕐 <b>{a['time']}–{end_str}</b> | {service.get('emoji', '')} {service.get('name', '')}\n"
            f"    {a['name']} | тел: {phone} | tg: {username}\n"
            f"    💰 {price} руб.\n"
        )

    lines.append(f"<b>Итого за день: {total} руб.</b>")
    await message.answer("\n".join(lines))


# =============================================
#  Любой текст
# =============================================
@router.message(F.text)
async def fallback(message: Message):
    await message.answer(
        "Используй меню ниже 👇\n"
        "Или нажми «💅 Записаться»!",
        reply_markup=main_menu(),
    )


# =============================================
#  Запуск
# =============================================
async def main():
    init_db()
    logger.info("Database initialized")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", minutes=5)
    scheduler.start()
    logger.info("Reminder scheduler started")

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
