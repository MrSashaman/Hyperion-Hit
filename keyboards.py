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


clicker_inline_kb = InlineKeyboardMarkup(row_width=1)
click_button = InlineKeyboardButton("🖱 Клик", callback_data="click")
balance_button = InlineKeyboardButton("💰 Баланс", callback_data="balance")
back_button = InlineKeyboardButton("⬅ Назад", callback_data="back_to_main")
clicker_inline_kb.add(click_button, balance_button, back_button)


# Главное меню
main_menu = ReplyKeyboardMarkup([
    [KeyboardButton("Кликер игра"), KeyboardButton("Камень, ножницы, бумага")],
    [KeyboardButton("Профиль"), KeyboardButton("Кейсы")]  # Добавлена кнопка "Кейсы"
], resize_keyboard=True)





# Меню камень, ножницы, бумага
rps_menu = ReplyKeyboardMarkup([
    [KeyboardButton("Сразиться с ботом"), KeyboardButton("Правила")]
], resize_keyboard=True, one_time_keyboard=True)

# Меню выбора хода в камень, ножницы, бумага
choice_menu = ReplyKeyboardMarkup([
    [KeyboardButton("Ножницы"), KeyboardButton("Бумага"), KeyboardButton("Камень")]
], resize_keyboard=True, one_time_keyboard=True)

# Меню кейсов
case_menu = ReplyKeyboardMarkup([
    [KeyboardButton("Открыть обычный кейс"), KeyboardButton("Купить обычный кейс")],
    [KeyboardButton("Открыть большой кейс"), KeyboardButton("Купить большой кейс")],
    [KeyboardButton("Открыть мега кейс"), KeyboardButton("Купить мега кейс")],
    [KeyboardButton("Открыть омега кейс"), KeyboardButton("Купить омега кейс")],
    [KeyboardButton("Открыть VIP кейс"), KeyboardButton("Купить VIP кейс")],
    [KeyboardButton("Открыть Снежный кейс"), KeyboardButton("Купить Снежный кейс")],
    [KeyboardButton("Назад")]
], resize_keyboard=True)
