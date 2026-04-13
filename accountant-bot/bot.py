import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from database import (
    init_db,
    save_user,
    get_user,
    update_user_field,
    save_income,
    get_income,
    save_payment,
    get_payments,
    clear_chat_history,
)
from tax_calculator import (
    calculate_usn_by_quarters,
    calculate_insurance_proportional,
    calculate_1pct_insurance,
    calculate_3ndfl_education_deduction,
    generate_usn_summary,
    format_money,
)
from knowledge_base import find_answer
from reminders import setup_default_reminders, check_and_send_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Команды бота ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username, user.full_name)

    welcome = (
        "👋 Привет! Я — ваш AI-бухгалтер.\n\n"
        "Помогу вам:\n"
        "📋 Подготовить закрывающую декларацию по УСН 6%\n"
        "💰 Рассчитать взносы и налоги\n"
        "📄 Сделать 3-НДФЛ на вычет за обучение\n"
        "🔔 Напомнить о сроках\n\n"
        "Команды:\n"
        "/income — внести доходы по кварталам\n"
        "/payments — внести уплаченные взносы/авансы\n"
        "/calculate — рассчитать налоги\n"
        "/status — что уже внесено\n"
        "/closeip — указать дату закрытия ИП\n"
        "/deduction — рассчитать вычет за об��чение\n"
        "/reset — начать заново\n"
        "/help — помощь\n\n"
        "Или просто напишите свой вопрос! 😊"
    )
    await update.message.reply_text(welcome)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 Команды бота:\n\n"
        "/income <квартал> <сумма> — внести доход\n"
        "  Пример: /income 1 250000\n\n"
        "/payments <квартал> <тип> <сумма> — внести платёж\n"
        "  Типы: advance (аванс УСН), insurance (взносы)\n"
        "  Пример: /payments 1 insurance 13414\n\n"
        "/calculate — рассчитать УСН за год\n"
        "/closeip <да��а> — указать дату закрытия ИП\n"
        "  ��ример: /closeip 2025-09-15\n\n"
        "/deduction <сумма обучения> <уплачено НДФЛ> — вычет\n"
        "  Пример: /deduction 120000 78000\n\n"
        "/status — показать все введ��нные данные\n"
        "/reset — очистить все данные и начать заново\n\n"
        "💬 Или напишите вопрос про: налоги, взносы, декларацию, вычет, штрафы, сроки"
    )
    await update.message.reply_text(help_text)


async def cmd_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id, update.effective_user.username, update.effective_user.full_name)

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Формат: /income <квартал> <��умма>\n"
            "��ример: /income 1 250000\n\n"
            "Или внесите все сразу:\n"
            "/income 1 250000 2 300000 3 200000 4 150000"
        )
        return

    try:
        i = 0
        added = []
        while i < len(args) - 1:
            quarter = int(args[i])
            amount = float(args[i + 1].replace(",", "."))
            if quarter < 1 or quarter > 4:
                await update.message.reply_text(f"❌ Квартал должен быть от 1 до 4, получено: {quarter}")
                return
            save_income(user_id, 2025, quarter, amount)
            added.append(f"  Q{quarter}: {format_money(amount)}")
            i += 2

        text = "✅ Доходы внесены:\n" + "\n".join(added)
        await update.message.reply_text(text)
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Неверный формат. Приме��: /income 1 250000")


async def cmd_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id, update.effective_user.username, update.effective_user.full_name)

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Формат: /payments <квартал> <тип> <сумма>\n\n"
            "Типы платежей:\n"
            "• advance — авансовый платёж УСН\n"
            "• insurance — ст��аховые взносы\n\n"
            "Пример: /payments 1 insurance 13414\n"
            "Пример: /payments 2 advance 5000"
        )
        return

    try:
        quarter = int(args[0])
        ptype = args[1].lower()
        amount = float(args[2].replace(",", "."))

        type_map = {"advance": "advance_usn", "insurance": "insurance_fixed"}
        if ptype not in type_map:
            await update.message.reply_text("❌ Тип: advance или insurance")
            return
        if quarter < 1 or quarter > 4:
            await update.message.reply_text("❌ Квартал от 1 до 4")
            return

        save_payment(user_id, 2025, quarter, type_map[ptype], amount)
        type_name = "Аванс УСН" if ptype == "advance" else "Страховые взносы"
        await update.message.reply_text(f"✅ {type_name} за Q{quarter}: {format_money(amount)}")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Неверный формат. Пример: /payments 1 insurance 13414")


async def cmd_calculate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    income_data = get_income(user_id, 2025)
    payments_data = get_payments(user_id, 2025)

    if not income_data:
        await update.message.reply_text("❌ Сначала внесите доходы командой /income")
        return

    insurance_by_q = {}
    advances_by_q = {}
    for q, types in payments_data.items():
        insurance_by_q[q] = types.get("insurance_fixed", 0)
        advances_by_q[q] = types.get("advance_usn", 0)

    result = calculate_usn_by_quarters(income_data, insurance_by_q, advances_by_q)
    summary = generate_usn_summary(result)

    total_income = sum(income_data.values())
    extra_1pct = calculate_1pct_insurance(total_income)

    user_data = get_user(user_id)
    insurance_info = ""
    if user_data and user_data.get("ip_closed_date"):
        ins = calculate_insurance_proportional(2025, user_data["ip_closed_date"])
        insurance_info = (
            f"\n\n📋 Страховые взносы (пропорционально):\n"
            f"  Дата закрытия ИП: {user_data['ip_closed_date']}\n"
            f"  Отработано дней: {ins['worked_days']} из {ins['total_days_in_year']}\n"
            f"  Фиксированные взносы: {format_money(ins['proportional_amount'])}\n"
            f"  1% с превышения: {format_money(extra_1pct)}\n"
            f"  Итого взнос��в: {format_money(ins['proportional_amount'] + extra_1pct)}"
        )
    elif extra_1pct > 0:
        insurance_info = (
            f"\n\n📋 Дополнительные взносы:\n"
            f"  1% с доходо�� свыше 300 000 ₽: {format_money(extra_1pct)}"
        )

    await update.message.reply_text(summary + insurance_info)


async def cmd_closeip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id, update.effective_user.username, update.effective_user.full_name)

    args = context.args
    if not args:
        await update.message.reply_text("Формат: /closeip 2025-09-15")
        return

    try:
        date_str = args[0]
        datetime.strptime(date_str, "%Y-%m-%d")
        update_user_field(user_id, "ip_closed_date", date_str)

        setup_default_reminders(user_id, date_str)

        from datetime import timedelta
        close_date = datetime.strptime(date_str, "%Y-%m-%d")
        decl_deadline = close_date + timedelta(days=25)
        ins_deadline = close_date + timedelta(days=15)

        await update.message.reply_text(
            f"✅ Дата ��акрытия ИП: {date_str}\n\n"
            f"⏰ Ваши дедлайны:\n"
            f"🔴 Уплата взносов до: {ins_deadline.strftime('%d.%m.%Y')} (15 дней)\n"
            f"🔴 Подача декларации до: {decl_deadline.strftime('%d.%m.%Y')} (25 дней)\n\n"
            f"🔔 Напоминания установлены!"
        )
    except ValueError:
        await update.message.reply_text("❌ Формат даты: ГГГГ-ММ-ДД (например 2025-09-15)")


async def cmd_deduction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Формат: /deduction <сумма обучения> <уплачено НДФЛ за год>\n"
            "Пример: /deduction 120000 78000"
        )
        return

    try:
        education = float(args[0])
        ndfl_paid = float(args[1])
        result = calculate_3ndfl_education_deduction(education, ndfl_paid)

        text = (
            f"📄 Расчёт вычета за обучение (3-НДФЛ):\n\n"
            f"  Расходы на обучение: {format_money(result['education_expenses'])}\n"
            f"  Лимит вычета: {format_money(result['max_deduction'])}\n"
            f"  Применённый вычет: {format_money(result['applied_deduction'])}\n"
            f"  Расчётный возврат (13%): {format_money(result['calculated_refund'])}\n"
            f"  Уплачен�� НДФЛ: {format_money(ndfl_paid)}\n\n"
            f"  💰 Вам вернут: {format_money(result['actual_refund'])}\n"
        )
        if result["limited_by_ndfl"]:
            text += "\n⚠️ Возврат ограничен суммой уплаченного НДФЛ."

        await update.message.reply_text(text)
    except ValueError:
        await update.message.reply_text("❌ Введите числа. Пример: /deduction 120000 78000")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    income_data = get_income(user_id, 2025)
    payments_data = get_payments(user_id, 2025)

    lines = ["📊 Ваши данные:\n"]

    if user_data:
        lines.append(f"ИНН: {user_data.get('inn') or 'не указан'}")
        lines.append(f"Дата закрыти�� ИП: {user_data.get('ip_closed_date') or 'не указана'}")
    else:
        lines.append("Профиль не создан. Напишите /start")

    lines.append("\nДоходы 2025:")
    if income_data:
        for q in range(1, 5):
            amt = income_data.get(q, 0)
            status = "✅" if amt > 0 else "⬜"
            lines.append(f"  {status} Q{q}: {format_money(amt)}")
    else:
        lines.append("  ⬜ Не внесены (/income)")

    lines.append("\nПлатежи 2025:")
    if payments_data:
        for q in range(1, 5):
            qtypes = payments_data.get(q, {})
            ins = qtypes.get("insurance_fixed", 0)
            adv = qtypes.get("advance_usn", 0)
            if ins > 0 or adv > 0:
                lines.append(f"  Q{q}: взносы={format_money(ins)}, аванс={format_money(adv)}")
    else:
        lines.append("  ⬜ Не внесены (/payments)")

    lines.append("\nГотовность:")
    has_income = bool(income_data)
    has_close = bool(user_data and user_data.get("ip_closed_date"))
    lines.append("  ✅ Доходы внесены" if has_income else "  ⬜ Доходы не внесены")
    lines.append("  ✅ Дата закрытия указан��" if has_close else "  ⬜ Дата закрытия н�� указана (/closeip)")
    lines.append(f"\n{'✅ Можно рассчитывать! /calculate' if has_income else '⬜ Внесите данные для расч��та'}")

    await update.message.reply_text("\n".join(lines))


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_chat_history(user_id)
    await update.message.reply_text(
        "🔄 История очищена.\n"
        "Данные о доходах и платежах сохранены.\n\n"
        "Напишите /start чтобы начать заново."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка свободного текста через базу знаний."""
    user = update.effective_user
    save_user(user.id, user.username, user.full_name)

    reply = find_answer(update.message.text)
    await update.message.reply_text(reply)


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать ��аботу"),
        BotCommand("income", "Внести доходы"),
        BotCommand("payments", "Внести платежи/взнос��"),
        BotCommand("calculate", "Ра��считать налоги"),
        BotCommand("closeip", "Указать дату закрыт��я ИП"),
        BotCommand("deduction", "Вычет ��а обучение"),
        BotCommand("status", "Показать статус"),
        BotCommand("help", "Помощь"),
        BotCommand("reset", "Начать заново"),
    ])

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_send_reminders,
        "interval",
        hours=1,
        args=[application.bot],
    )
    scheduler.start()


def main():
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("income", cmd_income))
    app.add_handler(CommandHandler("payments", cmd_payments))
    app.add_handler(CommandHandler("calculate", cmd_calculate))
    app.add_handler(CommandHandler("closeip", cmd_closeip))
    app.add_handler(CommandHandler("deduction", cmd_deduction))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
