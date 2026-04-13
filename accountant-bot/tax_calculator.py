"""
Модуль расчёта налогов для ИП на УСН 6% (доходы) без сотрудников.
Актуальные ставки и лимиты на 2025 год.
"""

from datetime import date, datetime
from math import ceil

# Фиксированные страховые взносы ИП за себя на 2025 год
FIXED_INSURANCE_2025 = 53_658  # ОПС + ОМС единым платежом
INCOME_THRESHOLD_1PCT = 300_000  # Порог для 1% допвзносов
USN_RATE = 0.06  # Ставка УСН "доходы"


def calculate_insurance_proportional(year: int, close_date_str: str) -> dict:
    """Рассчитать фиксированные взносы пропорционально отработанным дням."""
    close_date = datetime.strptime(close_date_str, "%Y-%m-%d").date()
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    total_days = (end - start).days + 1
    worked_days = (close_date - start).days + 1  # включая день закрытия

    proportional = round(FIXED_INSURANCE_2025 * worked_days / total_days, 2)

    return {
        "total_days_in_year": total_days,
        "worked_days": worked_days,
        "full_year_amount": FIXED_INSURANCE_2025,
        "proportional_amount": proportional,
    }


def calculate_1pct_insurance(total_income: float) -> float:
    """Рассчитать 1% с доходов свыше 300 000 ₽."""
    if total_income <= INCOME_THRESHOLD_1PCT:
        return 0.0
    return round((total_income - INCOME_THRESHOLD_1PCT) * 0.01, 2)


def calculate_usn_by_quarters(income_by_quarter: dict, insurance_paid_by_quarter: dict, advances_paid_by_quarter: dict) -> dict:
    """
    Рассчитать УСН 6% нарастающим итогом по кварталам.

    income_by_quarter: {1: 100000, 2: 200000, 3: 150000, 4: 50000}
    insurance_paid_by_quarter: {1: 13414, 2: 13414, 3: 13414, 4: 13416}
    advances_paid_by_quarter: {1: 0, 2: 5000, 3: 3000, 4: 0}
    """
    result = {}
    cumulative_income = 0
    cumulative_insurance = 0
    cumulative_advances = 0

    for q in range(1, 5):
        income_q = income_by_quarter.get(q, 0)
        insurance_q = insurance_paid_by_quarter.get(q, 0)
        advance_q = advances_paid_by_quarter.get(q, 0)

        cumulative_income += income_q
        cumulative_insurance += insurance_q
        cumulative_advances += advance_q

        # Налог нарастающим итогом
        tax_cumulative = round(cumulative_income * USN_RATE, 2)

        # Вычет взносов (ИП без сотрудников — 100%)
        tax_after_deduction = max(0, tax_cumulative - cumulative_insurance)

        # К уплате за квартал (минус ранее уплаченные авансы)
        to_pay = max(0, tax_after_deduction - cumulative_advances)

        result[q] = {
            "income_quarter": income_q,
            "income_cumulative": cumulative_income,
            "tax_cumulative": tax_cumulative,
            "insurance_cumulative": cumulative_insurance,
            "tax_after_deduction": tax_after_deduction,
            "advances_cumulative": cumulative_advances,
            "to_pay": round(to_pay, 2),
        }

        # Добавляем текущий аванс к кумулятивному (после расчёта)
        # Нет — аванс уже добавлен выше

    return result


def calculate_3ndfl_education_deduction(education_expenses: float, ndfl_paid: float) -> dict:
    """
    Рассчитать вычет за обучение по 3-НДФЛ.
    Лимит вычета за своё обучение — 150 000 ₽ (с 2024 года).
    """
    max_deduction = 150_000
    deduction = min(education_expenses, max_deduction)
    refund = round(deduction * 0.13, 2)
    actual_refund = min(refund, ndfl_paid)

    return {
        "education_expenses": education_expenses,
        "max_deduction": max_deduction,
        "applied_deduction": deduction,
        "calculated_refund": refund,
        "actual_refund": actual_refund,
        "limited_by_ndfl": refund > ndfl_paid,
    }


def format_money(amount: float) -> str:
    """Форматировать сумму в рублях."""
    return f"{amount:,.2f} ₽".replace(",", " ")


def generate_usn_summary(calc_result: dict) -> str:
    """Сгенерировать текстовый отчёт по УСН."""
    lines = ["📊 **Расчёт УСН 6% по кварталам:**\n"]

    for q in range(1, 5):
        data = calc_result.get(q)
        if not data:
            continue
        lines.append(f"**Квартал {q}:**")
        lines.append(f"  Доход за квартал: {format_money(data['income_quarter'])}")
        lines.append(f"  Доход нарастающим итогом: {format_money(data['income_cumulative'])}")
        lines.append(f"  Налог 6% нарастающим итогом: {format_money(data['tax_cumulative'])}")
        lines.append(f"  Вычет взносов: {format_money(data['insurance_cumulative'])}")
        lines.append(f"  Налог после вычета: {format_money(data['tax_after_deduction'])}")
        lines.append(f"  Уплачено авансов: {format_money(data['advances_cumulative'])}")
        lines.append(f"  **К уплате: {format_money(data['to_pay'])}**")
        lines.append("")

    # Итого за год
    last_q = calc_result.get(4) or calc_result.get(3) or calc_result.get(2) or calc_result.get(1)
    if last_q:
        lines.append(f"**ИТОГО за год:**")
        lines.append(f"  Общий доход: {format_money(last_q['income_cumulative'])}")
        lines.append(f"  Общий налог: {format_money(last_q['tax_cumulative'])}")
        lines.append(f"  Общий вычет: {format_money(last_q['insurance_cumulative'])}")
        lines.append(f"  Итого к уплате: {format_money(last_q['tax_after_deduction'])}")

    return "\n".join(lines)
