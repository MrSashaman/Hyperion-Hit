import random
import logging
import json
import asyncio
import time
from functools import wraps
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils import executor
from aiogram.utils.exceptions import BotKicked, ChatNotFound, TelegramAPIError
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# Путь к файлам
DATA_FILE = "users_data.json"
PROMO_FILE = "promocodes.json"
REFERRAL_COINS = 30000
REFERRAL_CASE = "big_case"
INVITER_COINS = 20000
INVITER_CASE = "normal_case"

# Уровни донатов
donation_levels = {
    "Игрок": {
        "tokens": 0,
        "daily_salary": 10000,
        "max_transfers": 2,
        "battle_delay": 60,  # задержка на сражение с ботом в КНБ
        "knb_delay": 60,  # задержка на сражение с ботом для КНБ
        "prefix": "Игрок",
        "unique_prefix": False,
        "vip_case": False,
        "daily_bonus": False
    },
    "Avenger": {
        "tokens": 39,
        "daily_salary": 25000,
        "max_transfers": 3,
        "battle_delay": 30,
        "knb_delay": 30,  # задержка на сражение с ботом для КНБ
        "prefix": "Avenger",
        "unique_prefix": True,
        "unique_icon": "[🔹]",
        "vip_case": False,
        "daily_bonus": True,
        "bonus": 32500
    },
    # Добавьте другие уровни донатов здесь
}

# Загрузка данных пользователей
def load_user_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
            return users
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Ошибка при загрузке данных пользователей: {e}")
        return {}

# Сохранение данных пользователей
# Пример использования перед сохранением данных
def save_user_data(users_data):
    try:
        # Обновляем все данные пользователей
        for user_id, user_data in users_data.items():
            users_data[user_id] = validate_and_update_user_data(user_data)  # Обновляем данные пользователя

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных пользователей: {e}")


# Загрузка данных о промокодах
def load_promo_data():
    try:
        with open(PROMO_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Ошибка при загрузке данных промокодов: {e}")
        return {}

# Сохранение данных о промокодах
def save_promo_data(promos):
    try:
        with open(PROMO_FILE, "w") as f:
            json.dump(promos, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных промокодов: {e}")



def get_user_data(user_id):
    global users  # Use the global 'users' variable

    user_id = str(user_id)

    if user_id == "7781701983":  # Replace with your bot's user ID to prevent issues
        logging.warning(f"Attempted to create data for bot with ID: {user_id}")
        return None  # Return None if it's the bot

    if user_id in users:
        return users[user_id]

    # If the user does not exist, create a new one
    users[user_id] = {
        "user_id": user_id,
        "clicks": 0,
        "coins": 0,
        "tokens": 0,
        "xp": 0,
        "vip": 0,
        "level": 1,
        "normal_case": 0,
        "big_case": 0,
        "mega_case": 0,
        "omega_case": 0,
        "snow_case": 0,
        "summer_case": 0,
        "vip_case": 0,
        "donate_case": 0,
        "daily_salary": 10000,
        "max_transfers": 2,
        "last_bonus_time": None,
        "referred_by": None,
        "referrals": [],
        "referral_reward_claimed": False,
        "banned": False,
        "matches": 0,
        "knb_delay": 60,
        "last_erireft_bonus": None,
        "donate_level": "Игрок",
        "played_rps": 0,
        "selected_boost_type": None,
        "active_boosts": {}
    }

    save_user_data(users)  # Save the data to your storage
    return users[user_id]  # Return the newly created user's data


# Генерация реферальной ссылки для пользователя
async def generate_referral_link(user_id: int, bot) -> str:
    """Генерирует реферальную ссылку для пользователя."""
    try:
        bot_username = (await bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user_id}"
        return referral_link
    except Exception as e:
        logging.error(f"Ошибка при генерации реферальной ссылки: {e}")
        return None

# Проверка и удаление просроченных бустов
def check_and_remove_expired_boosts(user_data):
    """Проверяет и удаляет просроченные бусты."""
    active_boosts = user_data.get("active_boosts", {})

    for boost_type, boost_data in list(active_boosts.items()):
        if boost_data.get("end_time", 0) < time.time():  # Если время действия буста истекло
            del active_boosts[boost_type]  # Удаляем буст из активных
            logging.info(f"Буст {boost_type} удалён, так как его время истекло.")
        else:
            logging.info(f"Буст {boost_type} ещё активен. Время окончания: {datetime.fromtimestamp(boost_data.get('end_time'))}")

    user_data["active_boosts"] = active_boosts  # Обновляем данные пользователя
    save_user_data(users)  # Сохраняем изменения в данных пользователя

promo_codes = load_promo_data()

class AdminPromoState(StatesGroup):
    waiting_for_type = State()
    waiting_for_promo_text = State()
    waiting_for_activations = State()
    waiting_for_reward = State()
    waiting_for_donation_name = State()
    waiting_for_donation_duration = State()
    waiting_for_gamepass_name = State()
    waiting_for_gamepass_duration = State()



# Миграция данных пользователей
def migrate_user_data():
    """Миграция данных: добавление новых полей в существующие данные пользователей."""
    global users
    updated = False  # Флаг, показывающий, были ли изменения

    # Проверяем, что users — это словарь
    if not isinstance(users, dict):
        logging.error("Ошибка: users не является словарем")
        return

    for user_id, user_data in users.items():
        # Проверяем, что user_data — это словарь
        if not isinstance(user_data, dict):
            logging.error(f"Ошибка: данные пользователя {user_id} не являются словарем")
            continue

        # Проверяем и корректируем каждое поле
        if "clicks" not in user_data or not isinstance(user_data["clicks"], int):
            user_data["clicks"] = 0
            updated = True
        if "bonus" not in user_data or not isinstance(user_data["bonus"], int):
            user_data["bonus"] = 1
            updated = True
        if "coins" not in user_data or not isinstance(user_data["coins"], int):
            user_data["coins"] = 0
            updated = True
        if "tokens" not in user_data or not isinstance(user_data["tokens"], int):
            user_data["tokens"] = 0
            updated = True
        if "xp" not in user_data or not isinstance(user_data["xp"], int):
            user_data["xp"] = 0
            updated = True
        if "vip" not in user_data or not isinstance(user_data["vip"], bool):
            user_data["vip"] = False
            updated = True
        if "level" not in user_data or not isinstance(user_data["level"], int):
            user_data["level"] = 1
            updated = True
        if "normal_case" not in user_data or not isinstance(user_data["normal_case"], int):
            user_data["normal_case"] = 0
            updated = True
        if "big_case" not in user_data or not isinstance(user_data["big_case"], int):
            user_data["big_case"] = 0
            updated = True
        if "mega_case" not in user_data or not isinstance(user_data["mega_case"], int):
            user_data["mega_case"] = 0
            updated = True
        if "omega_case" not in user_data or not isinstance(user_data["omega_case"], int):
            user_data["omega_case"] = 0
            updated = True
        if "snow_case" not in user_data or not isinstance(user_data["snow_case"], int):
            user_data["snow_case"] = 0
            updated = True
        if "vip_case" not in user_data or not isinstance(user_data["vip_case"], int):
            user_data["vip_case"] = 0
            updated = True
        if "donate_case" not in user_data or not isinstance(user_data["donate_case"], int):
            user_data["donate_case"] = 0
            updated = True
        if "daily_salary" not in user_data or not isinstance(user_data["daily_salary"], int):
            user_data["daily_salary"] = 10000
            updated = True
        if "max_transfers" not in user_data or not isinstance(user_data["max_transfers"], int):
            user_data["max_transfers"] = 2
            updated = True
        if "last_bonus_time" not in user_data:
            user_data["last_bonus_time"] = None
            updated = True
        if "referred_by" not in user_data:
            user_data["referred_by"] = None
            updated = True
        if "referrals" not in user_data:
            user_data["referrals"] = []
            updated = True
        if "referral_reward_claimed" not in user_data:
            user_data["referral_reward_claimed"] = False
            updated = True
        if "banned" not in user_data or not isinstance(user_data["banned"], bool):
            user_data["banned"] = False
            updated = True
        if "matches" not in user_data or not isinstance(user_data["matches"], int):
            user_data["matches"] = 0
            updated = True
        if "last_erireft_bonus" not in user_data:
            user_data["last_erireft_bonus"] = None
            updated = True
        if "donate_level" not in user_data:
            user_data["donate_level"] = "Игрок"
            updated = True
        if "played_rps" not in user_data or not isinstance(user_data["played_rps"], int):
            user_data["played_rps"] = 0
            updated = True
        if "selected_boost_type" not in user_data:
            user_data["selected_boost_type"] = None
            updated = True

    # Если были изменения, сохраняем обновленные данные
    if updated:
        save_user_data(users)
        print("Миграция данных пользователей завершена.")
    else:
        print("Миграция данных пользователей не требуется.")

# Загрузим данные пользователей
users = load_user_data()


def validate_and_update_user_data(user_data):
    """Проверка и коррекция данных пользователя перед сохранением"""
    if not isinstance(user_data.get("coins", 0), int):
        user_data["coins"] = 0
    if not isinstance(user_data.get("tokens", 0), int):
        user_data["tokens"] = 0
    if not isinstance(user_data.get("xp", 0), int):
        user_data["xp"] = 0
    if not isinstance(user_data.get("vip", False), bool):
        user_data["vip"] = False
    if user_data.get("last_bonus_time") is None:
        user_data["last_bonus_time"] = "2025-08-20T00:00:00"  # или другое значение по умолчанию

    # Повторите для всех других полей, если это необходимо
    return user_data


