"""
Автоматическая синхронизация записей с Google Календарём.

При новой записи — создаёт событие в календаре.
При отмене — удаляет событие.
В событии: имя клиента, телефон, услуга, цена.
"""

import os
import logging
from datetime import datetime, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "google_credentials.json")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

_service = None


def _get_service():
    """Возвращает Google Calendar API сервис (кэшируется)."""
    global _service
    if _service:
        return _service

    if not os.path.exists(CREDENTIALS_FILE):
        logger.warning("Google Calendar: файл google_credentials.json не найден — синхронизация отключена")
        return None

    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        logger.info("Google Calendar: подключено")
        return _service
    except Exception as e:
        logger.error(f"Google Calendar: ошибка подключения — {e}")
        return None


def create_event(
    date_str: str,
    time_str: str,
    duration_min: int,
    service_name: str,
    service_emoji: str,
    price: int,
    client_name: str,
    client_username: str | None = None,
    client_phone: str | None = None,
) -> str | None:
    """Создаёт событие в Google Календаре. Возвращает event_id или None."""
    service = _get_service()
    if not service:
        return None

    start_h, start_m = map(int, time_str.split(":"))
    start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_min)

    # Описание события
    desc_lines = [
        f"👤 Клиент: {client_name}",
    ]
    if client_username:
        desc_lines.append(f"📱 Telegram: @{client_username}")
    if client_phone:
        desc_lines.append(f"📞 Телефон: {client_phone}")
    desc_lines.append(f"💰 Сумма: {price} руб.")

    event = {
        "summary": f"{service_emoji} {service_name} — {client_name}",
        "description": "\n".join(desc_lines),
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Europe/Moscow",
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Europe/Moscow",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
            ],
        },
    }

    try:
        result = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        event_id = result.get("id")
        logger.info(f"Google Calendar: событие создано — {event_id}")
        return event_id
    except Exception as e:
        logger.error(f"Google Calendar: ошибка создания события — {e}")
        return None


def delete_event(event_id: str) -> bool:
    """Удаляет событие из Google Календаря."""
    service = _get_service()
    if not service or not event_id:
        return False

    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"Google Calendar: событие удалено — {event_id}")
        return True
    except Exception as e:
        logger.error(f"Google Calendar: ошибка удаления — {e}")
        return False
