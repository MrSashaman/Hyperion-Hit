from aiogram.utils import executor
from aiogram.utils.exceptions import BotKicked, ChatNotFound, TelegramAPIError
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
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

# Функция для получения цены
async def get_boost_price(boost_type: str, level: str):
    boost_prices = {
        "КНБ": {
            "1 Лвл буст": {"coins": 77000, "tokens": 59},
            "2 Лвл буст": {"coins": 100000, "tokens": 119},
            "3 Лвл буст": {"coins": 178000, "tokens": 249},
            "4 Лвл буст": {"coins": 400000, "tokens": 379},
            "5 Лвл буст": {"coins": 880500, "tokens": 469}
        },
        "Кликер": {
            "1 Лвл буст": {"coins": 50000, "tokens": 39},
            "2 Лвл буст": {"coins": 100000, "tokens": 59},
            "3 Лвл буст": {"coins": 125000, "tokens": 79},
            "4 Лвл буст": {"coins": 240000, "tokens": 119},
            "5 Лвл буст": {"coins": 580000, "tokens": 249}
        }
    }

    # Проверяем, что переданные значения корректны
    if boost_type in boost_prices and level in boost_prices[boost_type]:
        price = boost_prices[boost_type][level]["coins"]
        token_price = boost_prices[boost_type][level]["tokens"]
        return price, token_price
    return None, None



# 📌 Функция для отправки выбора уровня буста
async def send_boost_level(message: types.Message, boost_type: str):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    levels = {
        "КНБ": ["1 Лвл буст", "2 Лвл буст", "3 Лвл буст", "4 Лвл буст", "5 Лвл буст"],
        "Кликер": ["1 Лвл буст", "2 Лвл буст", "3 Лвл буст", "4 Лвл буст", "5 Лвл буст"]
    }

    if boost_type in levels:
        for level in levels[boost_type]:
            keyboard.add(level)

        keyboard.add("Назад")  # <--- ДО ОТПРАВКИ
        await message.answer(f"💥Выберите уровень для {boost_type}:", reply_markup=keyboard)
    else:
        await message.answer("❌ Неправильный тип буста.")