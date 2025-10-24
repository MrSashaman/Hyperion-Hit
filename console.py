from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import logging
from shared import bot
from utils import get_user_data, save_user_data, donation_levels, promo_codes, save_promo_data, AdminPromoState

# Функция для установки монет
async def set_coins(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 3:
        await message.answer("Использование: set_coins <user_id> <количество>")
        return
    target_user_id = parts[1]
    coins = int(parts[2])
    user_data = get_user_data(target_user_id)
    user_data['coins'] = coins
    save_user_data(users)
    await message.answer(f"Установлено {coins} монет для пользователя {target_user_id}")

# Функция для удаления монет
async def remove_coins(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 3:
        await message.answer("Использование: remove_coins <user_id> <количество>")
        return
    target_user_id = parts[1]
    coins_to_remove = int(parts[2])
    user_data = get_user_data(target_user_id)
    if user_data['coins'] < coins_to_remove:
        await message.answer("У пользователя недостаточно монет для списания.")
        return
    user_data['coins'] -= coins_to_remove
    save_user_data(users)
    await message.answer(f"У пользователя {target_user_id} было списано {coins_to_remove} монет.")

# Функция для установки уровня доната
async def set_donate(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) < 3:
        await message.answer("Использование: set_donate <user_id> <donate_level>")
        return

    target_user_id = parts[1]
    donate_level = " ".join(parts[2:])

    if donate_level not in donation_levels:
        await message.answer(f"❌ Уровень доната '{donate_level}' не найден.")
        return

    user_data = get_user_data(target_user_id)
    user_data['donate_level'] = donate_level
    donate_data = donation_levels[donate_level]

    user_data['daily_salary'] = donate_data['daily_salary']
    user_data['max_transfers'] = donate_data['max_transfers']
    user_data['vip_case'] = donate_data.get('vip_case', False)
    user_data['daily_bonus'] = donate_data.get('daily_bonus', False)

    save_user_data(users)
    await message.answer(f"✅ Установлен уровень доната '{donate_level}' для пользователя {target_user_id}")

# Функция для удаления уровня доната
async def remove_donate(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 3:
        await message.answer("Использование: remove_donate <user_id> <donate_level>")
        return

    target_user_id = parts[1]
    donate_level_to_remove = parts[2]

    user_data = get_user_data(target_user_id)

    if user_data.get('donate_level') != donate_level_to_remove:
        await message.answer(f"У пользователя нет такого уровня доната: {donate_level_to_remove}.")
        return

    user_data['donate_level'] = None
    user_data['daily_salary'] = 0
    user_data['max_transfers'] = 0
    user_data['vip_case'] = False
    user_data['daily_bonus'] = False

    save_user_data(users)
    await message.answer(f"У пользователя {target_user_id} был удален уровень доната {donate_level_to_remove}")

# Функция для добавления кейса пользователю
async def add_case(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 4:
        await message.answer("Использование: add_case <user_id> <тип_кейса> <количество>")
        return

    target_user_id = parts[1]
    case_type = parts[2]
    amount = int(parts[3])

    if case_type not in ["normal_case", "big_case", "mega_case", "omega_case", "vip_case", "snow_case", "donate_case", "summer_case"]:
        await message.answer("Неверный тип кейса.")
        return

    user_data = get_user_data(target_user_id)

    if case_type == "donate_case":
        user_data["donate_case"] += amount
        save_user_data(users)
        await message.answer(f"Добавлено {amount} донат кейсов для пользователя {target_user_id}")
    else:
        user_data[case_type] += amount
        save_user_data(users)
        await message.answer(f"Добавлено {amount} {case_type} для пользователя {target_user_id}")

# Функция для получения списка всех пользователей
async def get_users(message: types.Message, users: dict):
    await message.answer(str(users))

# Функция для создания промокода
async def create_promo(message: types.Message, state: FSMContext):
    await message.answer("Какой тип промокода вы хотите создать? (токены/донат/геймпасс)")
    await AdminPromoState.waiting_for_type.set()

# Функция для бана пользователя
async def ban_user(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 2:
        await message.answer("Использование: ban <user_id>")
        return

    target_user_id = parts[1]
    user_data = get_user_data(target_user_id)

    if user_data["banned"]:
        await message.answer(f"Пользователь {target_user_id} уже заблокирован.")
        return

    user_data["banned"] = True
    save_user_data(users)

    await message.answer(f"Пользователь {target_user_id} был заблокирован.")
    await bot.send_message(target_user_id, "❌ Вы заблокированы в боте.")

# Функция для разбана пользователя
async def unban_user(message: types.Message, command: str, users: dict):
    parts = command.split()
    if len(parts) != 2:
        await message.answer("Использование: unban <user_id>")
        return

    target_user_id = parts[1]
    user_data = get_user_data(target_user_id)

    if not user_data["banned"]:
        await message.answer(f"Пользователь {target_user_id} не заблокирован.")
        return

    user_data["banned"] = False
    save_user_data(users)

    await message.answer(f"Пользователь {target_user_id} был разблокирован.")
    await bot.send_message(target_user_id, "✅ Вы были разблокированы в боте.")
