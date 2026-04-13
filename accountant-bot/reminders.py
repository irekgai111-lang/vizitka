"""Модуль напоминаний о сроках сдачи отчётности."""

from datetime import datetime
from database import get_pending_reminders, mark_reminder_sent, save_reminder


# Стандартные налоговые дедлайны на 2025-2026
DEFAULT_DEADLINES = [
    ("2025-04-28", "⬜ Авансовый платёж УСН за 1 квартал 2025"),
    ("2025-07-28", "⬜ Авансовый платёж УСН за полугодие 2025"),
    ("2025-10-28", "⬜ Авансовый платёж УСН за 9 месяцев 2025"),
    ("2026-04-25", "⬜ Декларация по УСН за 2025 год (для ИП)"),
    ("2026-04-28", "⬜ Налог УСН за 2025 год"),
]


def setup_default_reminders(user_id: int, ip_closed_date: str = None):
    """Установить стандартные напоминания. Если ИП закрыто — рассчитать индивидуальные сроки."""
    if ip_closed_date:
        from datetime import timedelta
        close_date = datetime.strptime(ip_closed_date, "%Y-%m-%d")

        # 25 дней на подачу декларации
        decl_deadline = close_date + timedelta(days=25)
        save_reminder(user_id, "🔴 Срок подачи закрывающей декларации УСН!", decl_deadline.strftime("%Y-%m-%d"))

        # 15 дней на уплату взносов
        ins_deadline = close_date + timedelta(days=15)
        save_reminder(user_id, "🔴 Срок уплаты страховых взносов после закрытия ИП!", ins_deadline.strftime("%Y-%m-%d"))

        # Напоминание за 3 дня до каждого дедлайна
        if (decl_deadline - timedelta(days=3)) > datetime.now():
            save_reminder(user_id, "⚠️ Через 3 дня — дедлайн закрывающей декларации УСН!", (decl_deadline - timedelta(days=3)).strftime("%Y-%m-%d"))
        if (ins_deadline - timedelta(days=3)) > datetime.now():
            save_reminder(user_id, "⚠️ Через 3 дня — дедлайн уплаты взносов!", (ins_deadline - timedelta(days=3)).strftime("%Y-%m-%d"))
    else:
        for deadline_date, text in DEFAULT_DEADLINES:
            if datetime.strptime(deadline_date, "%Y-%m-%d") > datetime.now():
                save_reminder(user_id, text, deadline_date)


async def check_and_send_reminders(bot):
    """Проверить и отправить напоминания. Вызывается планировщиком."""
    today = datetime.now().strftime("%Y-%m-%d")
    reminders = get_pending_reminders(today)

    for reminder in reminders:
        try:
            await bot.send_message(
                chat_id=reminder["user_id"],
                text=f"🔔 **НАПОМИНАНИЕ**\n\n{reminder['reminder_text']}\n\nСрок: {reminder['remind_date']}",
                parse_mode="Markdown"
            )
            mark_reminder_sent(reminder["id"])
        except Exception as e:
            print(f"Ошибка отправки напоминания {reminder['id']}: {e}")
