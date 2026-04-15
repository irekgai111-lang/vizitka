"""
База данных для бота записи на маникюр.

Таблицы:
- users: клиенты
- appointments: записи (дата, время, услуга, статус)
"""

import sqlite3
from datetime import datetime, timedelta
from config import DATABASE_PATH

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# === Услуги и длительность ===

SERVICES = {
    "manicure": {"name": "Маникюр", "emoji": "💅", "duration": 90, "price": 1500},
    "pedicure": {"name": "Педикюр", "emoji": "🦶", "duration": 120, "price": 2000},
    "manicure_gel": {"name": "Маникюр + гель-лак", "emoji": "💅✨", "duration": 120, "price": 2500},
    "combo": {"name": "Маникюр + педикюр", "emoji": "💅🦶", "duration": 180, "price": 3500},
    "nail_repair": {"name": "Ремонт ногтя", "emoji": "🔧", "duration": 30, "price": 300},
    "removal": {"name": "Снятие покрытия", "emoji": "🧴", "duration": 30, "price": 500},
}

# Рабочие часы: 09:00–20:00, слоты по 30 мин
WORK_START = 9
WORK_END = 20
SLOT_MINUTES = 30


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT,
            phone TEXT
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            service_key TEXT NOT NULL,
            duration INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            reminded_6h INTEGER DEFAULT 0,
            reminded_2h INTEGER DEFAULT 0,
            reminded_1h INTEGER DEFAULT 0,
            google_event_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


# === Пользователи ===

def save_user(user_id: int, name: str, username: str | None):
    conn = get_db()
    conn.execute(
        """INSERT INTO users (id, name, username) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=?, username=?""",
        (user_id, name, username, name, username),
    )
    conn.commit()
    conn.close()


def save_phone(user_id: int, phone: str):
    conn = get_db()
    conn.execute("UPDATE users SET phone=? WHERE id=?", (phone, user_id))
    conn.commit()
    conn.close()


def get_user_phone(user_id: int) -> str | None:
    conn = get_db()
    row = conn.execute("SELECT phone FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return row["phone"] if row and row["phone"] else None


# === Расписание ===

def get_available_dates() -> list[dict]:
    """Ближайшие 7 рабочих дней (пн-сб)."""
    today = datetime.now()
    dates = []
    for i in range(1, 12):
        day = today + timedelta(days=i)
        if day.weekday() == 6:  # вс — выходной
            continue
        dates.append({
            "date": day.strftime("%Y-%m-%d"),
            "label": f"{DAY_NAMES[day.weekday()]} {day.strftime('%d.%m')}",
        })
        if len(dates) == 7:
            break
    return dates


def _all_slots() -> list[str]:
    """Все возможные слоты за день (каждые 30 мин)."""
    slots = []
    h, m = WORK_START, 0
    while h < WORK_END:
        slots.append(f"{h:02d}:{m:02d}")
        m += SLOT_MINUTES
        if m >= 60:
            h += 1
            m = 0
    return slots


def get_available_slots(date_str: str, duration_minutes: int) -> list[str]:
    """Свободные слоты на дату для услуги заданной длительности.

    Учитывает, что услуга занимает несколько слотов подряд.
    Например, маникюр 90 мин = 3 слота по 30 мин.
    """
    conn = get_db()
    booked = conn.execute(
        "SELECT time, duration FROM appointments WHERE date=? AND status='active'",
        (date_str,),
    ).fetchall()
    conn.close()

    # Множество занятых 30-мин слотов
    busy = set()
    for row in booked:
        start_h, start_m = map(int, row["time"].split(":"))
        dur = row["duration"]
        for offset in range(0, dur, SLOT_MINUTES):
            total_m = start_h * 60 + start_m + offset
            busy.add(f"{total_m // 60:02d}:{total_m % 60:02d}")

    all_slots = _all_slots()
    needed = duration_minutes // SLOT_MINUTES  # сколько слотов нужно

    available = []
    for i, slot in enumerate(all_slots):
        # Проверяем, что все нужные слоты свободны
        if i + needed > len(all_slots):
            break
        block = all_slots[i:i + needed]
        if all(s not in busy for s in block):
            # Проверяем, что услуга закончится до конца рабочего дня
            start_h, start_m = map(int, slot.split(":"))
            end_total = start_h * 60 + start_m + duration_minutes
            if end_total <= WORK_END * 60:
                available.append(slot)

    return available


# === Записи ===

def create_appointment(user_id: int, date_str: str, time_str: str,
                       service_key: str, duration: int, google_event_id: str | None = None) -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO appointments (user_id, date, time, service_key, duration, google_event_id) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, date_str, time_str, service_key, duration, google_event_id),
    )
    conn.commit()
    appt_id = cursor.lastrowid
    conn.close()
    return appt_id


def get_user_appointments(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM appointments
           WHERE user_id=? AND status='active' AND date >= date('now')
           ORDER BY date, time""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_appointment(appt_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if row:
        conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appt_id,))
        conn.commit()
    conn.close()
    return dict(row) if row else None


# === Напоминания (6ч, 2ч, 1ч) ===

def get_appointments_to_remind(hours: int) -> list[dict]:
    """Возвращает записи, для которых нужно отправить напоминание за N часов."""
    col = f"reminded_{hours}h"
    conn = get_db()
    rows = conn.execute(
        f"""SELECT * FROM appointments
           WHERE status='active' AND {col}=0
             AND datetime(date || ' ' || time) > datetime('now')
             AND datetime(date || ' ' || time) <= datetime('now', '+{hours} hour')"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminded(appt_id: int, hours: int):
    col = f"reminded_{hours}h"
    conn = get_db()
    conn.execute(f"UPDATE appointments SET {col}=1 WHERE id=?", (appt_id,))
    conn.commit()
    conn.close()


# === Админ ===

def get_appointments_for_date(date_str: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, u.name, u.username, u.phone
           FROM appointments a JOIN users u ON a.user_id = u.id
           WHERE a.date=? AND a.status='active'
           ORDER BY a.time""",
        (date_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
