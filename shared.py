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


TOKEN = "7781701983:AAE4hoJ2jJKQci-t2oCtvD6I4-nlFs_BVBQ"  # Замените своим токеном
bot = Bot(token=TOKEN)


level_xp = {
    2: 50,
    3: 80,
    4: 100,
    5: 200,
    6: 230,
    7: 500,
    8: 620,
    9: 900,
    10: 1320,
    11: 1560,
    12: 2780,
    13: 6000,
    14: 7620,
    15: 7800,
    16: 8000,
    17: 9100,
    18: 9450,
    19: 9760,
    20: 10000,
    21: 27199  # Максимальный уровень
}


level_rewards = {
    2: {"coins": 1000},
    3: {"coins": 1500},
    4: {"coins": 2500},
    5: {"coins": 3670},
    6: {"coins": 5000},
    7: {"coins": 7000},
    8: {"coins": 13400, "tokens": 4},
    9: {"coins": 15000, "tokens": 5},
    10: {"coins": 23000, "tokens": 7},
    11: {"coins": 25200, "tokens": 10},
    12: {"coins": 27500, "tokens": 12},
    13: {"coins": 30000, "big_case": 1},
    14: {"coins": 50000, "big_case": 2},
    15: {"coins": 70000, "big_case": 2, "mega_case": 1},
    16: {"coins": 80000, "big_case": 3, "mega_case": 2},
    17: {"coins": 90000, "big_case": 5, "mega_case": 3, "omega_case": 1},
    18: {"coins": 100000, "big_case": 8, "mega_case": 4, "omega_case": 1},
    19: {"coins": 120000, "normal_case": 1},
    20: {"coins": 200000, "tokens": 50, "snow_case": 1, "vip_case": 1}
}


case_prices = {
    "normal_case": 500,
    "big_case": 1000,
    "mega_case": 2500,
    "omega_case": 5000,
    "vip_case": 10000,
    "snow_case": 3000,
    "summer_case": 845000

}

case_rewards = {
    "normal_case": {(0, 450): 88, (451, 800): 72.2, (801, 1200): 65, (1201, 2000): 41.8},
    "big_case": {(0, 950): 76, (951, 1300): 64.73, (1301, 2000): 50.73, (2001, 3000): 39.33},
    "mega_case": {(0, 2300): 36.88, (2301, 3000): 66, (3001, 3780): 53, (3781, 4500): 48.92},
    "omega_case": {(0, 4500): 30, (5001, 6000): 62.19, (6001, 7500): 55, (7501, 10000): 33.98},
    "vip_case": {(0, 5000): 20, (5001, 6000): 60, (6001, 7000): 40, (7001, 10000): 25},
    "snow_case": {(0, 2500): 50, (2501, 5000): 75},
    "summer_case": {(20000, 60000): 65, (100000, 400000): 43, (1000000, 1500000): 41, (29, 99): 33, (0, 0): 2  # Ничего
}

}


# 🎯 Улучшения
upgrades = {
    "I улучшение": {"cost": 100, "bonus": 2},
    "II улучшение": {"cost": 300, "bonus": 5},
    "III улучшение": {"cost": 700, "bonus": 10},
    "IV улучшение": {"cost": 1500, "bonus": 20},
    "V улучшение": {"cost": 3000, "bonus": 40},
    "VI улучшение": {"cost": 6000, "bonus": 80},
}


# Привилегии и их бонусы
privilege_to_level_map = {
    "Зарплата Игрока": "Игрок",
    "Зарплата Авенжера": "Avenger",
    "Зарплата Титана": "Titan",
    "Зарплата Даркнесса": "Darkness",
    "Зарплата Д.Хелпера": "D.Helper",
    "Зарплата Лета": "Лето (Сезонный донат)",
    "Зарплата Хелпера": "Хелпер"
}

donate_levels_hierarchy = [
    "Игрок",
    "Avenger",
    "Titan",
    "Darkness",
    "D.Helper",
    "Лето (Сезонный донат)",
    "Хелпер"
]

