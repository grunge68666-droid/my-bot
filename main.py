"""
Telegram-бот опросник на aiogram 3.x с сохранением ответов в Google Sheets.

Функционал:
- Опрос из 5 вопросов, ответы сохраняются в Google Таблицу
- Уведомления администратору о новых ответах
- Команда /stats для просмотра статистики
- Команда /help для справки
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import gspread
from google.oauth2.service_account import Credentials

# =============================================================================
# КОНФИГУРАЦИЯ И ЛОГИРОВАНИЕ
# =============================================================================

# Загружаем переменные окружения из файла .env
load_dotenv()

# Получаем токен бота и ID администратора
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID", "")
CREDENTIALS_FILE: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# СОСТОЯНИЯ FSM (Finite State Machine)
# =============================================================================


class SurveyStates(StatesGroup):
    """Состояния для прохождения опроса."""

    waiting_for_name = State()       # Ожидаем ответ на вопрос 1
    waiting_for_age = State()        # Ожидаем ответ на вопрос 2
    waiting_for_activity = State()   # Ожидаем ответ на вопрос 3
    waiting_for_source = State()     # Ожидаем ответ на вопрос 4
    waiting_for_phone = State()      # Ожидаем ответ на вопрос 5


# =============================================================================
# ВОПРОСЫ ОПРОСА
# =============================================================================

QUESTIONS = [
    "Как вас зовут?",
    "Сколько вам лет?",
    "Какой у вас род деятельности?",
    "Откуда вы о нас узнали?",
    "Оставьте ваш телефон для связи.",
]

# Соответствие состояний и вопросов
STATE_QUESTION_MAP = {
    SurveyStates.waiting_for_name: 0,
    SurveyStates.waiting_for_age: 1,
    SurveyStates.waiting_for_activity: 2,
    SurveyStates.waiting_for_source: 3,
    SurveyStates.waiting_for_phone: 4,
}

# =============================================================================
# ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS
# =============================================================================


def get_google_client() -> Optional[gspread.Client]:
    """
    Создаёт клиент gspread для работы с Google Sheets.

    Returns:
        Клиент gspread или None при ошибке.
    """
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=scopes
        )
        client = gspread.authorize(creds)
        logger.info("Успешное подключение к Google Sheets.")
        return client
    except FileNotFoundError:
        logger.error(
            f"Файл учётных данных не найден: {CREDENTIALS_FILE}. "
            "Убедитесь, что JSON-ключ сервисного аккаунта находится в папке бота."
        )
    except Exception as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
    return None


def append_response_to_sheet(
    name: str, age: str, activity: str, source: str, phone: str
) -> bool:
    """
    Добавляет ответ пользователя в Google Таблицу.

    Args:
        name:  Имя пользователя.
        age:   Возраст пользователя.
        activity: Род деятельности.
        source:  Источник информации.
        phone:   Телефон для связи.

    Returns:
        True если успешно, False в противном случае.
    """
    client = get_google_client()
    if client is None:
        return False

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.sheet1  # Работаем с первым листом

        # Проверяем, есть ли заголовки; если нет — добавляем
        existing = worksheet.get_all_values()
        if not existing:
            headers = [
                "Дата и время",
                "Имя",
                "Возраст",
                "Род деятельности",
                "Источник",
                "Телефон",
            ]
            worksheet.append_row(headers)
            existing = [headers]

        # Добавляем строку с ответом
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [now, name, age, activity, source, phone]
        worksheet.append_row(row)
        logger.info(f"Ответ пользователя сохранён в Google Sheets: {name}")
        return True

    except Exception as e:
        logger.error(f"Ошибка при записи в Google Sheets: {e}")
        return False


# =============================================================================
# РОУТЕР И ОБРАБОТЧИКИ
# =============================================================================

router = Router()
# Словарь для временного хранения ответов пользователей
user_responses: Dict[int, Dict[str, str]] = {}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start — начало опроса."""
    await state.clear()
    user_responses[message.from_user.id] = {}

    welcome_text = (
        "👋 Привет! Я бот-опросник.\n\n"
        "Я задам вам 5 вопросов. Ваши ответы будут сохранены securely.\n"
        "Поехали!\n\n"
        f"{QUESTIONS[0]}"
    )

    await message.answer(welcome_text)
    await state.set_state(SurveyStates.waiting_for_name)


@router.message(SurveyStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Обработчик ответа на первый вопрос (имя)."""
    try:
        user_responses[message.from_user.id]["name"] = message.text.strip()

        await message.answer(f"Спасибо, {user_responses[message.from_user.id]['name']}!\n\n{QUESTIONS[1]}")
        await state.set_state(SurveyStates.waiting_for_age)
    except Exception as e:
        logger.error(f"Ошибка при обработке имени: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()


@router.message(SurveyStates.waiting_for_age)
async def process_age(message: Message, state: FSMContext) -> None:
    """Обработчик ответа на второй вопрос (возраст)."""
    try:
        user_responses[message.from_user.id]["age"] = message.text.strip()

        await message.answer(f"Отлично!\n\n{QUESTIONS[2]}")
        await state.set_state(SurveyStates.waiting_for_activity)
    except Exception as e:
        logger.error(f"Ошибка при обработке возраста: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()


@router.message(SurveyStates.waiting_for_activity)
async def process_activity(message: Message, state: FSMContext) -> None:
    """Обработчик ответа на третий вопрос (род деятельности)."""
    try:
        user_responses[message.from_user.id]["activity"] = message.text.strip()

        await message.answer(f"Понятно!\n\n{QUESTIONS[3]}")
        await state.set_state(SurveyStates.waiting_for_source)
    except Exception as e:
        logger.error(f"Ошибка при обработке рода деятельности: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()


@router.message(SurveyStates.waiting_for_source)
async def process_source(message: Message, state: FSMContext) -> None:
    """Обработчик ответа на четвёртый вопрос (источник)."""
    try:
        user_responses[message.from_user.id]["source"] = message.text.strip()

        await message.answer(f"Хорошо!\n\n{QUESTIONS[4]}")
        await state.set_state(SurveyStates.waiting_for_phone)
    except Exception as e:
        logger.error(f"Ошибка при обработке источника: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()


@router.message(SurveyStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext) -> None:
    """Обработчик ответа на пятый вопрос (телефон) — завершение опроса."""
    try:
        user_responses[message.from_user.id]["phone"] = message.text.strip()

        # Сохраняем все данные в Google Sheets
        data = user_responses[message.from_user.id]
        success = append_response_to_sheet(
            name=data["name"],
            age=data["age"],
            activity=data["activity"],
            source=data["source"],
            phone=data["phone"],
        )

        if success:
            thank_you = (
                "✅ Спасибо за прохождение опроса!\n\n"
                "Ваши ответы были успешно сохранены.\n"
                "Мы ценим ваше время!"
            )
            await message.answer(thank_you)

            # Отправляем уведомление администратору
            if ADMIN_ID:
                admin_msg = (
                    f"📨 Новый ответ!\n"
                    f"Пользователь @{message.from_user.username or message.from_user.first_name} "
                    f"({message.from_user.id}) завершил опрос."
                )
                try:
                    await bot.send_message(ADMIN_ID, admin_msg)
                    logger.info(f"Уведомление отправлено администратору: {ADMIN_ID}")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление администратору: {e}")
        else:
            await message.answer(
                "⚠️ Ваш ответ не удалось сохранить. "
                "Пожалуйста, свяжитесь с администратором."
            )

        # Очищаем состояние и временные данные
        await state.clear()
        user_responses.pop(message.from_user.id, None)

    except Exception as e:
        logger.error(f"Ошибка при завершении опроса: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()
        user_responses.pop(message.from_user.id, None)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Обработчик команды /stats — статистика для администратора."""
    # Проверяем, что пользователь — администратор
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    client = get_google_client()
    if client is None:
        await message.answer("❌ Не удалось подключиться к Google Sheets.")
        return

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.sheet1

        all_rows = worksheet.get_all_values()
        if not all_rows:
            await message.answer("📊 Статистика:\nЗавершённых опросов: 0")
            return

        # Первая строка — заголовки, остальные — данные
        total_responses = len(all_rows) - 1
        last_10 = all_rows[1:]  # Без заголовка

        # Формируем текст
        result = f"📊 Статистика опросов\n"
        result += f"Всего завершённых опросов: {total_responses}\n\n"

        if total_responses == 0:
            await message.answer(result)
            return

        # Последние 10 ответов
        recent = last_10[-10:] if len(last_10) >= 10 else last_10
        result += "📋 Последние ответы:\n"

        for i, row in enumerate(recent, 1):
            if len(row) >= 6:
                date_str = row[0]
                name_str = row[1]
                result += f"\n{i}. {date_str}\n"
                result += f"   Имя: {name_str}\n"
                result += f"   Возраст: {row[2]}\n"
                result += f"   Деятельность: {row[3]}\n"
                result += f"   Источник: {row[4]}\n"
                result += f"   Телефон: {row[5]}"

        await message.answer(result)
        logger.info(f"Администратор {message.from_user.id} запросил статистику")

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await message.answer("❌ Не удалось получить статистику. Проверьте подключение к Google Sheets.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help — справка по командам бота."""
    help_text = (
        "📖 Справка по командам бота:\n\n"
        "/start — Начать опрос\n"
        "/stats — Получить статистику (только для администратора)\n"
        "/help — Показать это сообщение\n\n"
        "Опрос состоит из 5 вопросов.\n"
        "Отвечайте по очереди — после каждого ответа будет следующий вопрос."
    )
    await message.answer(help_text)


@router.message()
async def echo_all(message: Message) -> None:
    """Перехватывает все несоответствующие команды сообщения."""
    # Игнорируем служебные сообщения
    if message.text and message.text.startswith("/"):
        await message.answer("⚠️ Неизвестная команда. Используйте /help для справки.")
    # Обычные сообщения в процессе опроса обрабатываются состояниями FSM


# =============================================================================
# ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА
# =============================================================================


async def main() -> None:
    """Точка входа в приложение бота."""
    # Проверяем наличие токена бота
    if not BOT_TOKEN:
        logger.error("ТОКЕН БОТА НЕ УКАЗАН! Добавьте BOT_TOKEN в файл .env")
        return

    if not SPREADSHEET_ID:
        logger.warning("SPREADSHEET_ID не указан — ответы не будут сохраняться в Google Sheets.")

    if not ADMIN_ID:
        logger.warning("ADMIN_ID не указан — уведомления администратору отключены.")

    # Создаём объекты бота и диспетчера
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Регистрируем роутер
    dp.include_router(router)

    logger.info("Бот запущен. Ожидание сообщений...")

    # Запускаем polling — бот начинает слушать Telegram API
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске polling: {e}")
    finally:
        await bot.session.close()


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
