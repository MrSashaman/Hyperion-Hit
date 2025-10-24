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

from boostutils import get_boost_price, send_boost_level
from console import add_case, remove_donate, set_donate, set_coins, ban_user, unban_user, remove_coins, get_users, create_promo
from keyboards import main_menu, rps_menu, clicker_inline_kb, case_menu
from utils import get_user_data, users, save_user_data, REFERRAL_COINS, REFERRAL_CASE, load_user_data, donation_levels, \
    promo_codes, AdminPromoState, save_promo_data, generate_referral_link, check_and_remove_expired_boosts, \
    validate_and_update_user_data

from utils import migrate_user_data
from shared import bot, case_prices, case_rewards, level_xp, level_rewards, upgrades, donate_levels_hierarchy, \
    privilege_to_level_map

# Initialize MemoryStorage
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)



# Определение путей к файлам


# Логирование ошибок
logging.basicConfig(level=logging.ERROR)











# Мигрируем данные пользователей (если необходимо)
migrate_user_data()








def check_ban(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = str(message.from_user.id)
        user = get_user_data(user_id)

        # Проверяем, заблокирован ли пользователь
        if user.get("banned", False):
            await message.answer("❌ Вы заблокированы в боте.")
            return

        return await func(message, *args, **kwargs)
    return wrapper


async def award_referral_bonus(referrer, user):
    """Awards both the referrer and the referred user."""
    # Ensure referrer gets the bonus
    if not referrer["referral_reward_claimed"]:
        referrer["coins"] += REFERRAL_COINS
        referrer[REFERRAL_CASE] += 1
        referrer["referral_reward_claimed"] = True  # Mark as rewarded
        save_user_data(users)
        await bot.send_message(referrer["user_id"], f"🎉 Поздравляем! Вы получили бонус за реферала: {REFERRAL_COINS} монет и 1 {REFERRAL_CASE}.")

    # Awarding the referred user as well
    user["coins"] += REFERRAL_COINS
    user[REFERRAL_CASE] += 1
    save_user_data(users)
    await bot.send_message(user["user_id"], f"🎉 Вы успешно зарегистрировались! Получаете бонус: {REFERRAL_COINS} монет и 1 {REFERRAL_CASE}.")















# 📌 Новый обработчик для команды /boost
@dp.message_handler(commands=['boost'])
@check_ban
async def handle_boost(message: types.Message):
    # Просто открываем меню выбора типа буста без проверки
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("КНБ", "Кликер")
    await message.answer("Добро пожаловать в отдел бустов⚡️! Выберите, для чего хотите купить буст:", reply_markup=keyboard)


@dp.message_handler(lambda message: message.text in ["КНБ", "Кликер"])
async def handle_boost_type(message: types.Message):
    boost_type = message.text
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Сохраняем выбранный тип буста в данных пользователя
    user_data["selected_boost_type"] = boost_type
    save_user_data(user_data)  # Исправлено на правильное сохранение данных

    await send_boost_level(message, boost_type)







@dp.message_handler(lambda message: message.text == "Назад")
async def go_back_from_boost_menu(message: types.Message):
    await start_command(message)




# 📌 Обработка выбора уровня буста
@dp.message_handler(
    lambda message: message.text in ["1 Лвл буст", "2 Лвл буст", "3 Лвл буст", "4 Лвл буст", "5 Лвл буст"])
async def handle_boost_level(message: types.Message):
    level = message.text
    level_num = int(level.split()[0])  # Извлекаем только число уровня, например 1 из "1 Лвл буст"

    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    boost_type = user_data.get("selected_boost_type")

    # Проверка, что для 5 уровня Кликера требуется минимум Titan
    if level_num == 5:
        user_level = user_data.get("donate_level", "Игрок")
        if not check_privilege_access(user_level, "Titan"):
            await message.answer("❌ Для покупки 5 Лвл буста требуется донат уровня Titan или выше.")
            return

    # Если boost_type не выбран, вернем ошибку
    if not boost_type:
        await message.answer("❌ Вы не выбрали тип буста! Попробуйте снова.")
        return

    # Проверка, если буст этого типа уже активирован, запретить покупку другого уровня
    if boost_type in user_data.get("active_boosts", {}):
        active_boost = user_data["active_boosts"][boost_type]
        active_level = int(active_boost["level"].split()[0])

        if active_level == level_num:
            # Получаем время окончания активного буста
            end_time = active_boost.get("end_time", 0)
            end_time_formatted = datetime.fromtimestamp(end_time).strftime("%d.%m.%Y %H:%M:%S")

            await message.answer(
                f"❌ У вас уже активирован буст {boost_type} {active_level} уровня.\n"
                f"⏳ Время окончания буста: {end_time_formatted}"
            )
            return
        else:
            await message.answer(
                f"❌ Вы уже купили буст {boost_type} {active_level} уровня. Вы не можете купить буст другого уровня.")

            return

    # Получаем цену для выбранного типа буста
    price, token_price = await get_boost_price(boost_type, level)

    if price is None or token_price is None:
        await message.answer("❌ Ошибка получения данных о цене. Попробуйте снова.")
        return

    # Определяем описание буста в зависимости от типа
    if boost_type == "КНБ":
        reward_map = {
            1: "💰 +110 монет и ⭐️ +30 XP",
            2: "💰 +165 монет и ⭐️ +45 XP",
            3: "💰 +220 монет и ⭐️ +75 XP",
            4: "💰 +275 монет и ⭐️ +105 XP",
            5: "💰 +385 монет и ⭐️ +150 XP"
        }
        reward_description = reward_map.get(level_num, "")
        boost_effect = f"Выдаёт при победе в КНБ: {reward_description}"
    elif boost_type == "Кликер":
        multiplier_map = {
            1: "🖱 x2 монеты за клик",
            2: "🖱 x3 монеты за клик",
            3: "🖱 x4 монеты за клик",
            4: "🖱 x5 монеты за клик",
            5: "🖱 x7 монет за клик"
        }
        boost_effect = multiplier_map.get(level_num, f"🖱 x{level_num} монет за клик")
    else:
        boost_effect = "Нет описания"

    boost_info = (
        f"💸 Покупка Буста {level_num} Уровня\n\n"
        f"Информация:\n"
        f"- {boost_effect}\n"
        f"Цена в монетах: {price}\n"
        f"Цена в токенах: {token_price}"
    )

    # Информация о способах оплаты
    info_text = boost_info + f"\nВыберите способ оплаты:"

    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Монеты", callback_data=f"pay_coins_{boost_type}_{level_num}"))
    keyboard.add(InlineKeyboardButton("Токены", callback_data=f"pay_tokens_{boost_type}_{level_num}"))
    await message.answer(info_text, reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('pay_'))
async def handle_payment_method(call: types.CallbackQuery):
    user_id = str(call.from_user.id)
    user_data = get_user_data(user_id)

    data_parts = call.data.split("_")

    if len(data_parts) != 4:
        await call.answer("❌ Ошибка при обработке данных. Попробуйте снова.", show_alert=True)
        return

    _, payment_method, boost_type, level_num = data_parts

    level_str = f"{level_num} Лвл буст"
    price, token_price = await get_boost_price(boost_type, level_str)

    # Если оплата монетами
    if payment_method == "coins":
        confirmation_message = f"🧾 Подтверждение оплаты Буста 🧾\n\n" \
                               f"Номер заказа: #{random.randint(10000, 99000)}\n\n" \
                               f"Цена в монетах составляет ~{price} монет.\n" \
                               f"Подтвердите покупку нажав на кнопку 'Оплатить✅'"
    # Если оплата токенами
    elif payment_method == "tokens":
        confirmation_message = f"🧾 Подтверждение оплаты Буста 🧾\n\n" \
                               f"Номер заказа: #{random.randint(10000, 99000)}\n\n" \
                               f"Цена в токенах составляет ~{token_price} токенов.\n" \
                               f"Подтвердите покупку нажав на кнопку 'Оплатить✅'"

    # Отправляем сообщение с кнопками
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Оплатить✅", callback_data=f"confirm_payment_{boost_type}_{level_num}"))
    keyboard.add(InlineKeyboardButton("Отмена❌", callback_data="cancel_payment"))

    # Delete the original message after sending the confirmation
    await call.message.delete()

    await call.message.answer(confirmation_message, reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "cancel_payment")
async def handle_cancel_payment(call: types.CallbackQuery):
    # Delete the confirmation message and inform the user about the cancellation
    await call.message.delete()

    await call.message.answer("🚫 Покупка буста отменена. Возврат в главное меню.", reply_markup=main_menu)
    await handle_boost(call.message)

@dp.callback_query_handler(lambda c: c.data.startswith('confirm_payment_'))
async def handle_payment_confirmation(call: types.CallbackQuery):
    user_id = str(call.from_user.id)
    user_data = get_user_data(user_id)

    data_parts = call.data.split("_")

    if len(data_parts) != 4:  # Проверяем длину на 4, так как нам нужно confirm, payment, boost_type и level_num
        await call.answer("❌ Ошибка при обработке данных. Попробуйте снова.", show_alert=True)
        return

    _, _, boost_type, level_num = data_parts

    level_str = f"{level_num} Лвл буст"
    price, token_price = await get_boost_price(boost_type, level_str)

    if user_data["coins"] >= price:
        user_data["coins"] -= price
    elif user_data["tokens"] >= token_price:
        user_data["tokens"] -= token_price
    else:
        await call.answer("❌ У вас недостаточно средств для покупки этого буста.", show_alert=True)
        return

    if "active_boosts" not in user_data:
        user_data["active_boosts"] = {}

    user_data["active_boosts"][boost_type] = {
        "level": level_num,
        "end_time": time.time() + 6 * 3600  # 6 часов
    }

    save_user_data(user_data)  # Сохраняем обновлённые данные пользователя

    # Delete the confirmation message after the purchase is successful
    await call.message.delete()

    await call.answer("✅ Буст успешно куплен! Наслаждайтесь!", show_alert=True)
    await call.message.edit_text("Вы выбрали буст. Наслаждайтесь!", reply_markup=main_menu)

























# 📌 Обработка донатов
@dp.message_handler(lambda message: message.text.startswith("Донат "))
async def process_donation(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user_data(user_id)

    donation_type = message.text.split(" ")[1]

    if donation_type in donation_levels:
        donation_details = donation_levels[donation_type]

        # Обновляем данные пользователя в соответствии с донатом
        user["tokens"] += donation_details["tokens"]
        user["daily_salary"] = donation_details["daily_salary"]
        user["max_transfers"] = donation_details["max_transfers"]
        user["vip"] = True
        user["vip_case"] = donation_details.get("vip_case", False)

        # Добавляем задержку для сражения с ботом
        user["knb_delay"] = donation_details.get("knb_delay", 60)  # задержка на сражение с ботом в КНБ

        if "xp_multiplier" in donation_details:
            user["xp_multiplier"] = donation_details["xp_multiplier"]
        if "exclusive_chat" in donation_details:
            user["exclusive_chat"] = True

        save_user_data(users)  # сохраняем изменения в данных пользователя

        await message.answer(f"🎉 Спасибо за приобретение {donation_type}! Вы теперь имеете:\n"
                             f"- {donation_details['tokens']} токенов\n"
                             f"- Зарплату в день: {donation_details['daily_salary']} монет\n"
                             f"- Максимум переводов в день: {donation_details['max_transfers']}.\n"
                             f"- Задержка на сражение с ботом в КНБ: {donation_details['knb_delay']} секунд.")

    else:
        await message.answer("❌ Некорректный уровень доната.")



def give_donate(user_id, donation_name, donation_duration):

    user = get_user_data(user_id)

    if donation_name not in donation_levels:
        print(f"Ошибка: Донат '{donation_name}' не существует!")
        return False

    user['vip'] = True
    user['tokens'] += donation_levels[donation_name]['tokens']
    user['daily_salary'] = donation_levels[donation_name]['daily_salary']
    user['max_transfers'] = donation_levels[donation_name]['max_transfers']
    user['vip_case'] = donation_levels[donation_name].get('vip_case', False)

    if 'xp_multiplier' in donation_levels[donation_name]:
        user['xp_multiplier'] = donation_levels[donation_name]['xp_multiplier']
    if 'exclusive_chat' in donation_levels[donation_name]:
        user['exclusive_chat'] = True

    save_user_data(users)
    return True



class PromoCodeState(StatesGroup):
    waiting_for_promocode = State()




@dp.message_handler(commands=['promocode'])
@check_ban
async def activate_promo(message: types.Message, state: FSMContext):
    await message.answer("⚠️Введите пожалуйста промокод❗️")
    await PromoCodeState.waiting_for_promocode.set()

@dp.message_handler(state=PromoCodeState.waiting_for_promocode)
async def process_promocode(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    promo_code = message.text

    if promo_code not in promo_codes:
        await message.answer("💮Этого промокода не существует, или у него закончились активации!❌")
        await state.finish()
        return

    if user_id in promo_codes[promo_code]["used_by"]:
        await message.answer("Вы уже активировали этот промокод.")
        await state.finish()
        return

    if promo_codes[promo_code]["activations"] <= 0:
        await message.answer("💮Этого промокода не существует, или у него закончились активации!❌")
        # Удаление промокода, если активации закончились
        del promo_codes[promo_code]
        save_promo_data(promo_codes)
        await state.finish()
        return

    promo_type = promo_codes[promo_code]["type"]
    user = get_user_data(user_id)
    reward_message = ""

    if promo_type == "токены":
        tokens = int(promo_codes[promo_code]["reward"])
        user["tokens"] += tokens
        reward_message = f"{tokens} токенов"

    elif promo_type == "донат":
        donation_name = promo_codes[promo_code]["donation_name"]
        donation_duration = promo_codes[promo_code]["donation_duration"]

        reward_message = f"Донат '{donation_name}' на {donation_duration} дней"
        print(f"Выдать донат {donation_name} пользователю {user_id} на {donation_duration} дней")

        user_data = get_user_data(user_id)
        user_data['donate_level'] = donation_name
        user_data['donation_duration'] = donation_duration

        # Применяем бонусы или изменения, связанные с донатом
        donation_data = promo_codes[promo_code]  # Например, бонусы могут быть определены в promo_codes
        user_data['vip_access'] = donation_data.get('vip_access', False)
        user_data['extra_slots'] = donation_data.get('extra_slots', 0)

        save_user_data(users)
        await message.answer(f"Вы получили донат: {reward_message}")
        print(f"Донат '{donation_name}' на {donation_duration} дней выдан пользователю {user_id}")

    elif promo_type == "геймпасс":
        gamepass_name = promo_codes[promo_code]["gamepass_name"]
        gamepass_duration = promo_codes[promo_code]["gamepass_duration"]
        reward_message = f"Геймпас '{gamepass_name}' на {gamepass_duration} дней"
        print(f"Выдать геймпас {gamepass_name} пользователю {user_id} на {gamepass_duration} дней")

        # Включаем VIP статус
        user["vip"] = True  # Устанавливаем VIP статус в True

        # Сохраняем изменения в базе данных
        save_user_data(users)

        await message.answer(f"Вы получили геймпас: {reward_message}\n")
        print(f"Геймпас '{gamepass_name}' на {gamepass_duration} дней выдан пользователю {user_id}")



    else:
        await message.answer("Ошибка: Неизвестный тип промокода.")
        await state.finish()
        return


    # Обновляем данные о промокоде
    promo_codes[promo_code]["activations"] -= 1
    promo_codes[promo_code]["used_by"].append(user_id)

    # Удаляем промокод, если активации закончились
    if promo_codes[promo_code]["activations"] <= 0:
        del promo_codes[promo_code]
        save_promo_data(promo_codes)

    save_user_data(users)

    await message.answer(f"⚡@{message.from_user.username}, ты успешно активировал промокод🔥\n"
                         f"Ты получил награду в виде: {reward_message} ")

    await state.finish()





ADMIN_IDS = [5680132288, 7778928973, 5899698992]

@dp.message_handler(commands=['console'])
@check_ban
async def admin_console(message: types.Message, state: FSMContext):
    """Консоль для администрирования."""
    user_id = message.from_user.id

    # Проверка прав администратора
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return

    command = message.get_args()
    if not command:
        await message.answer("📜 Доступные команды:\n"
                             "🔧 Управление балансом:\n"
                             "/set_coins <user_id> <количество> — установить количество коинов\n"
                             "/remove_coins <user_id> <количество> — убрать коины\n"
                             "/remove_tokens <user_id> <количество> — убрать токены\n"
                             "\n🎁 Кейсы:\n"
                             "/add_case <user_id> <тип_кейса> <количество> — выдать кейсы пользователю\n"
                             "\n💎 Донат:\n"
                             "/set_donate <user_id> <donate_level> — установить уровень доната\n"
                             "/remove_donate <user_id> <donate_level> — понизить донат-уровень\n"
                             "\n👥 Пользователи:\n"
                             "/get_users — вывести список всех пользователей\n"
                             "\n🎟 Промокоды:\n"
                             "/create_promo — создать новый промокод")
        return

    try:
        if command.startswith("set_coins"):
            await set_coins(message, command, users)

        elif command.startswith("remove_coins"):
            await remove_coins(message, command, users)

        elif command.startswith("set_donate"):
            await set_donate(message, command, users)

        elif command.startswith("remove_donate"):
            await remove_donate(message, command, users)

        elif command.startswith("add_case"):
            await add_case(message, command, users)

        elif command == "get_users":
            await get_users(message, users)

        elif command.startswith("create_promo"):
            await create_promo(message, state)

        elif command.startswith("ban"):
            await ban_user(message, command, users)

        elif command.startswith("unban"):
            await unban_user(message, command, users)

        else:
            await message.answer("Неизвестная команда.")

    except Exception as e:
        await message.answer(f"Произошла ошибка: {e}")


# 📌 Обработчик для создания промокода
@dp.message_handler(state=AdminPromoState.waiting_for_type)
async def admin_create_promo_type(message: types.Message, state: FSMContext):
    promo_type = message.text.lower()
    if promo_type not in ["токены", "донат", "геймпасс"]:
        await message.answer("Неверный тип промокода. Доступные типы: токены, донат, геймпасс")
        await state.finish()
        return

    await state.update_data(promo_type=promo_type)
    await message.answer("Введите текст промокода (который должен ввести пользователь):")
    await AdminPromoState.waiting_for_promo_text.set()


# 📌 Обработчик ввода текста промокода
@dp.message_handler(state=AdminPromoState.waiting_for_promo_text)
async def admin_create_promo_text(message: types.Message, state: FSMContext):
    promo_text = message.text

    if promo_text in promo_codes:
        await message.answer("Такой промокод уже существует!")
        await state.finish()
        return
    await state.update_data(promo_text=promo_text)
    await message.answer("Введите количество активаций:")
    await AdminPromoState.waiting_for_activations.set()


# 📌 Обработчик ввода количества активаций
@dp.message_handler(state=AdminPromoState.waiting_for_activations)
async def admin_create_promo_activations(message: types.Message, state: FSMContext):
    try:
        activations = int(message.text)
        if activations <= 0:
            await message.answer("Количество активаций должно быть больше нуля.")
            await state.finish()
            return
    except ValueError:
        data = await state.get_data()
        attempts = data.get("activation_attempts", 0) + 1

        if attempts >= 3:
            await message.answer("❌ Превышено количество попыток. Создание промокода отменено.")
            await state.finish()
            return

        await state.update_data(activation_attempts=attempts)
        await message.answer(
            f"❌ Неверный формат количества активаций. Осталось попыток: {3 - attempts}. Введите число:")
        return

    await state.update_data(activations=activations)
    data = await state.get_data()
    promo_type = data['promo_type']

    if promo_type == "токены":
        await message.answer("Введите количество токенов, которые получит пользователь:")
        await AdminPromoState.waiting_for_reward.set()
    elif promo_type == "донат":
        await message.answer("Введите название доната:")
        await AdminPromoState.waiting_for_donation_name.set()
    elif promo_type == "геймпасс":
        await message.answer("Введите название геймпасса:")
        await AdminPromoState.waiting_for_gamepass_name.set()


# 📌 Обработчик ввода награды для промокода (токены)
@dp.message_handler(state=AdminPromoState.waiting_for_reward)
async def admin_create_promo_reward(message: types.Message, state: FSMContext):
    reward = message.text
    await state.update_data(reward=reward)
    await create_admin_promo(message, state)


# 📌 Обработчик ввода названия доната для промокода (донат)
@dp.message_handler(state=AdminPromoState.waiting_for_donation_name)
async def admin_create_promo_donation_name(message: types.Message, state: FSMContext):
    donation_name = message.text.strip()

    data = await state.get_data()
    attempts = data.get("donation_name_attempts", 0)

    if donation_name not in donation_levels:
        attempts += 1
        await state.update_data(donation_name_attempts=attempts)

        if attempts >= 3:
            await message.answer("❌ Превышено количество попыток. Создание промокода отменено.")
            await state.finish()
        else:
            await message.answer(
                f"❌ Донат '{donation_name}' не найден. Осталось попыток: {3 - attempts}. Попробуйте снова:")
        return

    await state.update_data(donation_name=donation_name)
    await message.answer("✅ Введите срок действия доната (в днях):")
    await AdminPromoState.waiting_for_donation_duration.set()



# 📌 Обработчик ввода срока действия доната для промокода
@dp.message_handler(state=AdminPromoState.waiting_for_donation_duration)
async def admin_create_promo_donation_duration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    attempts = data.get("donation_duration_attempts", 0)

    try:
        donation_duration = int(message.text.strip())
        if donation_duration <= 0:
            raise ValueError
    except ValueError:
        attempts += 1
        await state.update_data(donation_duration_attempts=attempts)

        if attempts >= 3:
            await message.answer("❌ Превышено количество попыток. Создание промокода отменено.")
            await state.finish()
        else:
            await message.answer(f"❌ Неверный срок действия. Осталось попыток: {3 - attempts}. Введите заново:")
        return

    await state.update_data(donation_duration=donation_duration)
    await create_admin_promo(message, state)


# 📌 Обработчик ввода названия геймпасса для промокода
@dp.message_handler(state=AdminPromoState.waiting_for_gamepass_name)
async def admin_create_promo_gamepass_name(message: types.Message, state: FSMContext):
    gamepass_name = message.text
    await state.update_data(gamepass_name=gamepass_name)
    await message.answer("Введите срок действия геймпасса (в днях):")
    await AdminPromoState.waiting_for_gamepass_duration.set()


# 📌 Обработчик ввода срока действия геймпасса для промокода
@dp.message_handler(state=AdminPromoState.waiting_for_gamepass_duration)
async def admin_create_promo_gamepass_duration(message: types.Message, state: FSMContext):
    try:
        gamepass_duration = int(message.text)
        if gamepass_duration <= 0:
            await message.answer("Срок действия должен быть больше нуля.")
            await state.finish()
            return
    except ValueError:
        await message.answer("Неверный формат срока действия. Введите число.")
        await state.finish()
        return
    await state.update_data(gamepass_duration=gamepass_duration)
    await create_admin_promo(message, state)


# 📌 Создание промокода для админа
async def create_admin_promo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    promo_type = data['promo_type']
    promo_text = data['promo_text']
    activations = data['activations']
    reward = data.get('reward')
    donation_name = data.get('donation_name')
    donation_duration = data.get('donation_duration')
    gamepass_name = data.get('gamepass_name')
    gamepass_duration = data.get('gamepass_duration')

    promo_codes[promo_text] = {
        "type": promo_type,
        "reward": reward,
        "activations": activations,
        "used_by": [],
        "donation_name": donation_name,
        "donation_duration": donation_duration,
        "gamepass_name": gamepass_name,
        "gamepass_duration": gamepass_duration
    }
    save_promo_data(promo_codes)

    info = f"Промокод успешно создан:\nТекст промокода: {promo_text}\nТип: {promo_type}\nАктиваций: {activations}\n"
    if promo_type == "токены":
        info += f"Награда: {reward} токенов"
    elif promo_type == "донат":
        info += f"Донат: {donation_name}, Срок: {donation_duration} дней"
    elif promo_type == "геймпасс":
        info += f"Геймпас: {gamepass_name}, Срок: {gamepass_duration} дней"

    await message.answer(info)
    await state.finish()


@dp.message_handler(commands=['donate'])
@check_ban
async def donate_command(message: types.Message):
    info_message = "<b>💸 Доступные Донаты:</b>\n\n"

    info_message += (
        "<blockquote><b>👤 Игрок</b> — 0₽\n"
        "<i>💰 Зарплата: 10 000 монет в день</i>\n"
        "<i>🔄 Переводов в день: 2</i>\n"
        "<i>⏱️ Задержка КНБ: 45 сек</i>\n"
        "<i>🔹 Префикс: Игрок</i>\n"
        "<i>🚫 Уникальный префикс: Нет</i></blockquote>\n\n"

        "<blockquote><b>⚔️ Avenger</b> — 39₽\n"
        "<i>💰 Зарплата: 25 000 монет в день</i>\n"
        "<i>🔄 Переводов в день: 3</i>\n"
        "<i>⏱️ Задержка КНБ: 30 сек</i>\n"
        "<i>🔹 Префикс: Avenger</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🎁 Бонус при покупке: 32 500 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i></blockquote>\n\n"

        "<blockquote><b>💪 Titan</b> — 59₽\n"
        "<i>💰 Зарплата: 35 000 монет в день</i>\n"
        "<i>🔄 Переводов в день: 8</i>\n"
        "<i>⏱️ Задержка КНБ: 20 сек</i>\n"
        "<i>🔹 Префикс: Титан</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🧰 Доступ к VIP-кейсу</i>\n"
        "<i>🎁 Бонус при покупке: 50 000 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i></blockquote>\n\n"

        "<blockquote><b>🌑 Darkness</b> — 109₽\n"
        "<i>💰 Зарплата: 85 000 монет в день</i>\n"
        "<i>🔄 Переводов в день: 12</i>\n"
        "<i>⏱️ Задержка КНБ: 10 сек</i>\n"
        "<i>🔹 Префикс: Darkness</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🧰 Доступ к VIP-кейсу</i>\n"
        "<i>🎁 Бонус при покупке: 150 000 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i></blockquote>\n\n"

        "<blockquote><b>🛠 D.Helper</b> — 329₽\n"
        "<i>💰 Зарплата: 350 000 монет в день</i>\n"
        "<i>🔄 Переводы: без ограничений</i>\n"
        "<i>⏱️ Задержка КНБ: 5 сек</i>\n"
        "<i>🔹 Префикс: Д.Хелпер</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🧰 Доступ к VIP-кейсу</i>\n"
        "<i>🔐 Доступ к закрытому чату</i>\n"
        "<i>🎁 Бонус при покупке: 600 000 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i></blockquote>\n\n"

        "<blockquote><b>☀️ Лето (Сезонный)</b> — 349₽\n"
        "<i>💰 Зарплата: 350 000 монет в день</i>\n"
        "<i>🔄 Переводы: без ограничений</i>\n"
        "<i>⏱️ Задержка КНБ: 5 сек</i>\n"
        "<i>🔹 Префикс: Лето</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🧰 Доступ к VIP-кейсу</i>\n"
        "<i>🔐 Доступ к закрытому чату</i>\n"
        "<i>🎁 Бонус при покупке: 600 000 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i>\n"
        "<i>📅 Доступен до 31.08.2025</i>\n"
        "<i>🎁 Возможность открывать Летний Кейс</i></blockquote>\n\n"

        "<blockquote><b>🧙‍♂️ Хелпер</b> — 555₽\n"
        "<i>💰 Зарплата: 450 000 монет в день</i>\n"
        "<i>🔄 Переводы: без ограничений</i>\n"
        "<i>⏱️ Задержка КНБ: 3 сек</i>\n"
        "<i>🔹 Префикс: Хелпер</i>\n"
        "<i>✅ Уникальный префикс</i>\n"
        "<i>🧰 Доступ к VIP-кейсу</i>\n"
        "<i>🔐 Доступ к закрытому чату</i>\n"
        "<i>🎁 Бонус при покупке: 1 000 000 монет</i>\n"
        "<i>🎉 Ежедневный бонус</i></blockquote>\n\n"
    )

    info_message += "<b>📩 Для покупки: пишите в поддержку — @Sashaerireft </b>"

    try:
        await message.answer(info_message, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Error sending message: {e}")









@dp.message_handler(commands=['game'])
@check_ban
async def games_command(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user_data(user_id)
    referrer_id = message.get_args()

    if referrer_id and referrer_id.isdigit() and int(referrer_id) != int(user_id):  # Prevent self-referral
        referrer_id = str(int(referrer_id))
        referrer = get_user_data(referrer_id)  # Load data of referrer

        if user["referred_by"] is None:  # User wasn't referred yet
            user["referred_by"] = referrer_id
            save_user_data(users)  # save immediately

            referrer["referrals"].append(user_id)
            save_user_data(users)

            await bot.send_message(referrer_id,
                                   f"🎉 Твой реферал @{message.from_user.username} успешно перешёл по твоей ссылке!")
            await message.answer("🎉 Вы успешно зарегистрировались по реферальной ссылке!")
        else:
            await message.answer("Вы уже зарегистрированы по реферальной ссылке.")

    await message.answer("🏓 Выбери игру:", reply_markup=main_menu)  # Display main menu

# 📌 Обработчик старта
# 📌 Обработчик старта
@dp.message_handler(commands=['start'])
@check_ban
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user_data(user_id)  # No need to pass 'users'


    if user is None:
        await message.answer("❌ Ошибка: пользователь не найден. Попробуйте снова.")
        return

    # Process referrer ID (from referral link)
    referrer_id = message.get_args()
    if referrer_id and referrer_id.isdigit() and int(referrer_id) != int(user_id):
        referrer_id = str(int(referrer_id))
        referrer = get_user_data(referrer_id)  # Load referrer's data

        if user["referred_by"] is None:  # Ensure the user hasn't been referred yet
            user["referred_by"] = referrer_id
            referrer["referrals"].append(user_id)  # Add user to referrer's referral list
            save_user_data(users)  # Save immediately

            # Приглашённый получает свой бонус сразу (30,000 монет и 1 большой кейс)
            user["coins"] += 30000  # 30,000 монет
            user["big_case"] += 1  # 1 большой кейс
            await message.answer("🎉 Вы успешно зарегистрировались по реферальной ссылке! Получено: 💰 30,000 монет и 1 большой кейс!")

            # Сохраняем данные пользователя
            save_user_data(users)

            # Уведомление для реферера
            await bot.send_message(referrer_id, f"🎉 Твой реферал @{message.from_user.username} успешно зарегистрировался по твоей ссылке!")

        else:
            await message.answer("Вы уже зарегистрированы по реферальной ссылке.")



    # Теперь используем user_name в сообщении
    await message.answer(f"💎 Привет @{message.from_user.username}! Ты попал в бота Hyperion Legacy")

    # Проверка уровня пользователя и начисление бонуса для реферера, если уровень >= 2
    # Бонус начисляется только если пользователь достиг 2 уровня и бонус ещё не был начислен
    if user["level"] >= 2 and user["referred_by"]:
        inviter = get_user_data(user["referred_by"])

        # Проверка, чтобы бонус не начислялся повторно
        if inviter and not inviter.get("referral_reward_claimed", False):
            # Начисляем бонусы рефереру (20,000 монет и 1 обычный кейс)
            inviter["coins"] += 20000  # 20,000 монет
            inviter["normal_case"] += 1  # 1 обычный кейс
            inviter["referral_reward_claimed"] = True  # Помечаем, что бонус был начислен
            save_user_data(users)  # Сохраняем изменения

            # Уведомление для реферера
            await bot.send_message(inviter["user_id"], f"🎉 Ваш реферал @{message.from_user.username} достиг уровня 2 и вы получили бонус!")
            print("Реферер получил бонус за реферала, достигшего уровня 2.")




# Меню улучшений
upgrade_menu = ReplyKeyboardMarkup([
    [KeyboardButton(name) for name in upgrades.keys()],
    [KeyboardButton("Назад")]
], resize_keyboard=True, one_time_keyboard=True)


@dp.callback_query_handler(lambda c: c.data == 'back_to_main')
async def handle_back_to_main(call: types.CallbackQuery):
    await call.message.answer("🏓 Выбери игру:", reply_markup=main_menu)


@dp.message_handler(commands=['erireft'])
@check_ban
async def erireft_bonus(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user_data(user_id)

    now = datetime.utcnow()
    if user["banned"]:
        await message.answer("❌ Вы заблокированы в боте.")
        return

    if user['last_erireft_bonus']:
        last_bonus_time = datetime.fromisoformat(user['last_erireft_bonus'])
        time_since_last_bonus = now - last_bonus_time

        if time_since_last_bonus < timedelta(days=14):
            remaining_time = timedelta(days=14) - time_since_last_bonus
            hours, remainder = divmod(remaining_time.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            await message.answer(
                f"🔮Ты уже забирал бонус! Вернись через {int(hours)}ч {int(minutes)}м {int(seconds)}с."
            )
            return

    # Выдаём бонус
    user["coins"] += 350
    user["xp"] += 25
    user["last_erireft_bonus"] = now.isoformat()  # Обновляем время последнего бонуса

    save_user_data(users)

    await message.answer(
        f"<b>🔥Поздравляю {message.from_user.username}! Ты получил бонус от Эрирефт'а в размере: 350 монет и 25 XP</b>",
        parse_mode="HTML"  # Ensure HTML is used to parse the bold tag
    )


@dp.message_handler(commands=['referral'])
@check_ban
async def referral_command(message: types.Message):
    user_id = str(message.from_user.id)

    # Генерация реферальной ссылки
    referral_link = await generate_referral_link(user_id, bot)

    if referral_link:
        markup = InlineKeyboardMarkup()
        # Используем ссылку для отправки через Telegram с предзаполненным текстом
        markup.add(InlineKeyboardButton("Пригласить друга", url=f"https://t.me/share/url?url={referral_link}"))

        # Отправка сообщения с реферальной ссылкой
        await message.answer(
            "🔗 Реферальная программа:\n\n"
            "<blockquote>"
            "👤 Каждый приглашённый друг получает бонус в виде 30,000 монет и 1 Большого кейса.\n\n"
            "💎 Награда в виде 20,000 монет и 1 обычного кейса начисляется тебе, когда приглашённый друг достигнет 2 уровня.\n\n"
            "</blockquote>"
            f"📖 Используй свою персональную ссылку для приглашений: {referral_link}",  # No quote for the link
            reply_markup=markup,
            parse_mode="HTML"  # parse_mode should be here only once
        )

    else:
        await message.answer("❌ Не удалось сгенерировать реферальную ссылку. Попробуйте позже.")


# 📌 Обработка реферальной ссылки
@dp.callback_query_handler(lambda c: c.data.startswith("referral"))
async def handle_referral_link(call: types.CallbackQuery):
    referral_code = call.data.split(":")[1]  # Извлекаем код реферала из ссылки
    user_id = str(call.from_user.id)

    # Получаем данные пользователя и реферера
    user = get_user_data(user_id)
    inviter = get_user_data(referral_code)  # Реферер

    # Проверка, был ли пользователь уже зарегистрирован по реферальной ссылке
    if not user.get("referred_by"):  # Если пользователь ещё не был пригашён
        # Привязка пользователя к рефералу
        user["referred_by"] = referral_code  # Сохраняем, кто пригласил пользователя
        if referral_code not in user["referrals"]:
            user["referrals"].append(referral_code)  # Добавляем в список рефералов

        # Начисляем бонусы новому пользователю
        user["coins"] += 20000  # 20,000 монет
        user["normal_case"] += 1  # 1 обычный кейс

        # Сохраняем данные пользователя
        save_user_data(users)

        # Отправляем сообщение новому пользователю
        await call.message.answer(
            f"🎉 Вы успешно зарегистрировались по реферальной ссылке!\n\n"
            f"Получено:\n"
            f"💰 20,000 монет и 1 обычный кейс!\n\n"
            f"Ваш пригласивший друг {referral_code} получил:\n"
            f"💰 30,000 монет и 1 большой кейс!"
        )

        # Уведомление для реферера (только в момент регистрации)
        await bot.send_message(referral_code, f"🎉 Твой реферал @{call.from_user.username} успешно зарегистрировался по твоей ссылке!")

    else:
        await call.message.answer("❌ Вы уже зарегистрированы по реферальной ссылке.")

    # Proceed to main menu
    await call.message.answer("🏓 Выбери игру:", reply_markup=main_menu)


# 📌 Обработка обновления уровня пользователя и начисления бонусов для реферера
async def check_and_award_referral_bonus(user_id):
    user = get_user_data(user_id)

    if user["level"] >= 2 and user["referred_by"]:  # Проверяем, если уровень >= 2 и был реферальный код
        inviter_id = user["referred_by"]
        inviter = get_user_data(inviter_id)

        # Проверяем, что реферер ещё не получил бонус
        if inviter and not inviter.get("referral_reward_claimed", False):  # Если реферер не получил бонус
            # Начисляем бонус для реферера
            inviter["coins"] += 20000  # 20,000 монет
            inviter["normal_case"] += 1  # 1 обычный кейс
            inviter["referral_reward_claimed"] = True  # Помечаем, что бонус был начислен

            # Сохраняем данные реферера
            save_user_data(users)

            # Уведомляем реферера
            await bot.send_message(inviter_id, f"🎉 Ваш реферал @{user['user_id']} достиг уровня 2 и вы получили бонус!")
            print(f"Реферер @{user['user_id']} получил бонус за достижение уровня 2.")







@dp.message_handler(lambda message: message.text == "Кликер игра")
@check_ban
async def start_clicker_game(message: types.Message):
    await message.answer("📀 Кликер меню", reply_markup=clicker_inline_kb)

@dp.callback_query_handler(lambda c: c.data == "balance")
async def balance_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user = get_user_data(user_id)

    if user["banned"]:
        await callback_query.answer("❌ Вы заблокированы в боте.", show_alert=True)
        return

    clicks = user.get("clicks", 0)
    coins = user.get("coins", 0)
    await callback_query.answer(f"🖱 Клики: {clicks} | 💰 Монеты: {coins}", show_alert=True)




async def process_case_action(user_id: int, case_type: str, action: str) -> str:
    user_id = str(user_id)
    user = get_user_data(user_id)

    if action == "open":
        if case_type == 'donate_case':
            # Обработка для донат кейса
            return await process_donate_case(user_id)

        if user[case_type] <= 0:
            logging.info(f"Запрос от пользователя: {user_id}, тип кейса: {case_type}")
            return f"У вас нет {case_type.replace('_', ' ')} для открытия!"


        reward_ranges = case_rewards.get(case_type)
        if not reward_ranges:
            return f"Ошибка: {case_type} не имеет наград."

        total_chance = sum(reward_ranges.values())
        random_value = random.uniform(0, total_chance)
        cumulative_chance = 0

        reward_amount = 0
        for reward_range, chance in reward_ranges.items():
            cumulative_chance += chance
            if random_value <= cumulative_chance:
                reward_amount = random.randint(reward_range[0], reward_range[1])
                break

        user["coins"] += reward_amount
        user[case_type] -= 1
        save_user_data(users)  # Save after modification
        return f"Вы открыли {case_type.replace('_', ' ')} и получили {reward_amount} монет!"

    elif action == "buy":
        case_price = case_prices.get(case_type)
        if not case_price:
            return f"Ошибка: {case_type} не существует."

        if user["coins"] < case_price:
            return f"Недостаточно монет! Цена {case_type.replace('_', ' ')}: {case_price} монет."

        user["coins"] -= case_price
        user[case_type] += 1
        save_user_data(users)  # Save after modification
        return f"Вы купили {case_type.replace('_', ' ')} за {case_price} монет!"

    else:
        return "Неизвестное действие"


# 📌 Баланс
@dp.message_handler(lambda message: message.text == "Баланс")
@check_ban
async def balance(message: types.Message):
    user_id = message.from_user.id
    user = get_user_data(user_id)

    if user["banned"]:
        await message.answer("❌ Вы заблокированы в боте.")
        return

    await message.answer(
        f"📊 Твой баланс:\n🔹 Клики: {user['clicks']}\n💰 Монеты: {user['coins']}\n⭐️ XP: {user['xp']}\nУровень: {user['level']}")


## 📌 Покупка улучшений
@dp.message_handler(lambda message: message.text in upgrades.keys())
async def buy_upgrade(message: types.Message):
    user_id = message.from_user.id
    user = get_user_data(user_id)

    upgrade = message.text
    cost = upgrades[upgrade]["cost"]
    bonus = upgrades[upgrade]["bonus"]

    if user["banned"]:
        await message.answer("❌ Вы заблокированы в боте.")
        return

    if user["coins"] >= cost:
        user["coins"] -= cost
        user["bonus"] += bonus
        save_user_data(users)  # Save after buying upgrade
        await message.answer(f"✅ Ты купил {upgrade}!\nТеперь каждый клик даёт +{bonus} бонуса.")
    else:
        await message.answer(f"❌ Недостаточно монет!\nСтоимость: {cost}, твои монеты: {user['coins']}.")


# 📌 Выбор улучшений
@dp.message_handler(lambda message: message.text == "Список улучшений")
async def show_upgrades(message: types.Message):
    await message.answer("Выбери улучшение:", reply_markup=upgrade_menu)



# 📌 Назад в главное меню
@dp.message_handler(lambda message: message.text == "Назад")
async def back_to_main(message: types.Message):
    if message.reply_markup == upgrade_menu or message.reply_markup == case_menu or message.reply_markup == rps_menu:  # Added case_menu
        await message.answer("📀 Кликер меню", reply_markup=clicker_inline_kb)
    else:
        await message.answer("🏓 Выбери игру:", reply_markup=main_menu)



@dp.callback_query_handler(lambda c: c.data == 'click')
async def handle_click(call: types.CallbackQuery):
    user_id = str(call.from_user.id)
    user = get_user_data(user_id)
    user_data = get_user_data(user_id)


    check_and_remove_expired_boosts(user_data)  # Удаляем просроченные бусты


    if user.get("banned"):
        await call.answer("❌ Вы заблокированы.", show_alert=True)
        return

    # Начальный множитель для обычных пользователей
    click_multiplier = 1

    # Проверка на VIP
    is_vip = user.get("vip", False)
    if is_vip:
        click_multiplier *= 2  # Удваиваем клики для VIP
        print(f"VIP активирован! Удвоенные клики.")

    # Получаем активный буст для Кликера
    boost = user.get("active_boosts", {}).get("Кликер")

    # Проверяем, что буст активен и его уровень
    if boost and boost.get("end_time", 0) > time.time():  # Если буст активен
        level = boost.get("level")

        # Проверяем уровень буста и применяем соответствующий множитель
        boost_levels = {
            "1": 2,  # Уровень 1: x2 клики
            "2": 3,  # Уровень 2: x3 клики
            "3": 4,  # Уровень 3: x4 клики
            "4": 5,  # Уровень 4: x5 клики
            "5": 7,  # Уровень 5: x7 клики
        }

        boost_click_multiplier = boost_levels.get(level, 1)
        click_multiplier *= boost_click_multiplier  # Умножаем на множитель буста

        # Логируем уровень и множитель
        print(f"Активный буст для Кликера: уровень {level}, множитель: {boost_click_multiplier}")

    else:
        # Логируем, что буст не активен
        print("Буст для Кликера не активен или время истекло.")

    # Рассчитываем количество кликов с учетом множителей
    clicks_reward = user.get("bonus", 1) * click_multiplier
    user["clicks"] = user.get("clicks", 0) + clicks_reward  # Увеличиваем количество кликов

    # Монеты остаются без изменений
    coins_reward = 1  # 1 монета за клик

    user["coins"] = user.get("coins", 0) + coins_reward  # Добавляем монеты за клик

    save_user_data(users)
    await call.answer(f"+{coins_reward} монет 💰, +{clicks_reward} кликов 💥", show_alert=False)





# 📌 Обработчик для игры "Камень, ножницы, бумага"
@dp.message_handler(lambda message: message.text == "Камень, ножницы, бумага")
@check_ban
async def rps_game(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    # Если у пользователя есть активный буст
    check_and_remove_expired_boosts(user_data)  # Удаляем просроченные бусты
    active_boost = user_data.get("active_boost")
    boost_multiplier = 1
    xp_multiplier = 1

    # Проверка на наличие активного буста для игры КНБ
    if active_boost and active_boost["boost_type"] == "КНБ":
        boost_level = active_boost["level"]
        if boost_level == "1 Лвл":
            boost_multiplier = 2
            xp_multiplier = 2
        elif boost_level == "2 Лвл":
            boost_multiplier = 3
            xp_multiplier = 3
        elif boost_level == "3 Лвл":
            boost_multiplier = 4
            xp_multiplier = 5
        elif boost_level == "4 Лвл":
            boost_multiplier = 5
            xp_multiplier = 7
        elif boost_level == "5 Лвл":
            boost_multiplier = 7
            xp_multiplier = 10

    # Проверка на наличие VIP статуса
    # Checking if VIP status is active
    is_vip = user_data.get("vip", False) and user_data.get("vip_expiration", 0) > time.time()

    # Если у пользователя есть VIP, множители увеличиваются
    # If the user has VIP status, the boost multiplier is doubled
    if is_vip:
        boost_multiplier = 2
        xp_multiplier = 2
        print(f"VIP активирован для пользователя {user_id}! Удвоенные монеты и XP.")

    await message.answer(f"📀 Привет! Чтобы сыграть в камень, ножницы, бумага, выбери с кем хочешь сразиться!⚔️", reply_markup=rps_menu)

# 📌 Обработчик для кнопки "Правила"
@dp.message_handler(lambda message: message.text == "Правила")
async def rps_rules(message: types.Message):
    await message.answer(
        "📜 Правила игры:\n"
        "Камень побеждает ножницы.\n"
        "Ножницы побеждают бумагу.\n"
        "Бумага побеждает камень.\n"
        "В случае ничьи, монеты не взимаются.\n"
        "При выигрыше у бота вы получаете монеты и опыт.\n"
        "При проигрыше боту с вас взимается 100 монет (если они есть).\n"
    )

# 📌 Выбор сражения с ботом
@dp.message_handler(lambda message: message.text == "Сразиться с ботом")
async def rps_vs_bot(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    # Получаем время последнего сражения
    last_battle_time = user_data.get("last_battle_time", 0)
    current_time = time.time()

    # Проверяем, можно ли снова сразиться с ботом на основе задержки KNB
    if current_time - last_battle_time < user_data.get("knb_delay", 45):
        remaining_time = user_data["knb_delay"] - (current_time - last_battle_time)
        minutes, seconds = divmod(remaining_time, 45)
        await message.answer(f"❌ Подождите {int(minutes)} минут и {int(seconds)} секунд перед следующим боем.")
        return

    # Если задержка прошла, обновляем время последнего сражения и показываем меню выбора
    user_data["last_battle_time"] = current_time
    save_user_data(users)

    # Если уже был сделан выбор, блокируем дальнейший выбор
    if user_data.get("has_made_choice", False):
        await message.answer("❌ Вы уже сделали выбор для этого сражения. Подождите, пока оно завершится.")
        return

    # Отображаем меню выбора, если выбора еще не было
    available_choices = ["Ножницы", "Бумага", "Камень"]
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    for choice in available_choices:
        keyboard.add(KeyboardButton(choice))

    await message.answer("‼️ Выберите, что хотите поставить:", reply_markup=keyboard)

# 📌 Обработчик выбора хода в КНБ (Камень, Ножницы, Бумага)
@dp.message_handler(lambda message: message.text in ["Ножницы", "Бумага", "Камень"])
async def rps_play(message: types.Message):
    user_id = message.from_user.id
    user = get_user_data(user_id)

    player_choice = message.text
    bot_choice = random.choice(["Ножницы", "Бумага", "Камень"])

    # Получаем время последнего действия и задержку
    current_time = time.time()
    last_action_time = user.get("last_action_time", 0)

    # Получаем задержку из данных пользователя в зависимости от уровня доната
    donate_level = user.get("donate_level", "Игрок")
    knb_delay = 45  # По умолчанию для Игрока 60 секунд

    # Задержки для разных донатов
    if donate_level == "Avenger":
        knb_delay = 30
    elif donate_level == "Titan":
        knb_delay = 20
    elif donate_level == "Darkness":
        knb_delay = 10
    elif donate_level == "D.Helper" or donate_level == "Лето (Сезонный донат)":
        knb_delay = 5
    elif donate_level == "Хелпер":
        knb_delay = 3

    # Проверка, не выбрал ли игрок ход слишком быстро
    if current_time - last_action_time < knb_delay:
        remaining_time = knb_delay - (current_time - last_action_time)
        minutes, seconds = divmod(remaining_time, 60)
        await message.answer(f"❌ Подождите {int(minutes)} минут и {int(seconds)} секунд перед следующим действием.")
        return

    # Обновляем время последнего действия
    user["last_action_time"] = current_time
    save_user_data(users)

    # Проверка, не выбрал ли игрок тот же ход, что и до этого
    last_choice = user.get("last_choice", None)

    # Если игрок уже выбрал ход, запретить выбрать его снова
    if last_choice == player_choice:
        await message.answer(f"❌ Вы уже выбрали {player_choice}. Подождите завершения сражения.")
        return

    # Сохраняем выбор игрока
    user["last_choice"] = player_choice  # Сохраняем выбранный ход
    save_user_data(users)

    # Проверка на наличие активного буста для КНБ
    boost_multiplier = 1
    xp_multiplier = 1
    boost = user.get("active_boosts", {}).get("КНБ")

    # Логика для активации бустов
    if boost:
        print(f"Время окончания буста: {boost.get('end_time', 0)}")
        if boost.get("end_time", 0) > time.time():  # Проверяем, что время еще не истекло
            level = boost.get("level")
            boost_multipliers = {
                "1": (2, 2),  # Уровень 1: x2 монеты, x2 XP
                "2": (3, 3),  # Уровень 2: x3 монеты, x3 XP
                "3": (4, 5),  # Уровень 3: x4 монеты, x5 XP
                "4": (5, 7),  # Уровень 4: x5 монеты, x7 XP
                "5": (7, 10),  # Уровень 5: x7 монеты, x10 XP
            }
            boost_multiplier, xp_multiplier = boost_multipliers.get(level, (1, 1))

            # Учитываем, что VIP уже удваивает множители, если он активен
            print(f"Активный буст для КНБ: {boost}, множитель монет: {boost_multiplier}, множитель XP: {xp_multiplier}")
        else:
            print("Буст для КНБ не активен или время истекло.")
            boost = None  # Сбрасываем буст, если время истекло
    else:
        print("Активный буст не найден.")

    # Обновляем счётчик сыгранных матчей
    user["played_rps"] = user.get("played_rps", 0) + 1

    # Для VIP увеличиваем шанс на победу
    is_vip = user.get("vip", False)
    print(f"VIP статус: {is_vip}")  # Логирование VIP статуса

    if is_vip:
        win_chance = 0.66  # 66% шанс для VIP
        print("Для VIP шанс на победу: 66%.")
    else:
        win_chance = 0.33  # 33% шанс для обычных пользователей
        print("Для обычных пользователей шанс на победу: 33%.")

    # Логика для определения победителя на основе выбранных ходов
    if random.random() < win_chance:  # Если случайное число меньше шанса на победу
        # Проверка по правилам игры "Камень, Ножницы, Бумага"
        if (player_choice == "Камень" and bot_choice != "Бумага") or \
           (player_choice == "Бумага" and bot_choice != "Ножницы") or \
           (player_choice == "Ножницы" and bot_choice != "Камень"):
            outcome = "win"
        else:
            outcome = "lose"
    else:
        # Проигрывает игрок
        if (player_choice == "Камень" and bot_choice == "Бумага") or \
           (player_choice == "Бумага" and bot_choice == "Ножницы") or \
           (player_choice == "Ножницы" and bot_choice == "Камень"):
            outcome = "lose"
        else:
            outcome = "win"

    # Определяем победителя или ничью
    if player_choice == bot_choice:
        outcome = "draw"  # Ничья

    # Обработка ничьей
    if outcome == "draw":
        await message.answer(f"Ничья! Ты выбрал {player_choice}, бот выбрал {bot_choice}.")
    elif outcome == "win":
        # Применяем множители для монет и XP
        coins_reward = 110 * boost_multiplier * (2 if is_vip else 1)
        xp_reward = 30 * xp_multiplier * (2 if is_vip else 1)

        user["coins"] = user.get("coins", 0) + coins_reward
        user["xp"] = user.get("xp", 0) + xp_reward

        old_level = user.get("level", 1)
        new_level = await check_level_up(message, user_id)

        if new_level > old_level:
            user["level"] = new_level  # <- сохраняем новый уровень!
            user["xp"] = 0  # Сбрасываем XP после повышения уровня
            await message.answer(f"🎉 Поздравляем, ты повысил уровень до {new_level}! 🎉")
            level_up_message = await give_level_reward(user_id, new_level)
            await message.answer(level_up_message)
        else:
            await message.answer(
                f"Ты выиграл! Ты выбрал {player_choice}, бот выбрал {bot_choice}.\n"
                f"💰 +{coins_reward} монет, ⭐️ +{xp_reward} XP."
            )
    else:
        user["games_lost"] = user.get("games_lost", 0) + 1
        if user.get("coins", 0) >= 100:
            user["coins"] -= 100
            await message.answer(f"Ты проиграл! Ты выбрал {player_choice}, бот выбрал {bot_choice}.\n-100 монет.")
        else:
            await message.answer(
                f"Ты проиграл! Ты выбрал {player_choice}, бот выбрал {bot_choice}.\nУ тебя недостаточно монет.")

    # После завершения сражения сбрасываем выбор игрока, чтобы он мог снова выбрать
    user["last_choice"] = None  # Сбрасываем выбор игрока
    user["has_made_choice"] = False  # Сбрасываем флаг, чтобы можно было выбрать новый ход
    save_user_data(users)

    save_user_data(users)






async def check_level_up(message: types.Message, user_id: int) -> int:
    user = users.get(str(user_id), {})
    current_level = user.get("level", 1)
    xp = user.get("xp", 0)

    # Проверка уровня на основе XP
    for level, xp_threshold in sorted(level_xp.items()):
        if xp >= xp_threshold:
            current_level = level
        else:
            break

    # Если уровень достиг 2, начисляем бонус рефереру (если ещё не начислен)
    if current_level >= 2 and user.get("referred_by") and not user.get("referral_reward_claimed", False):
        referrer_id = user["referred_by"]
        referrer = get_user_data(referrer_id)

        if referrer and not referrer.get("referral_reward_claimed", False):  # Проверяем, что бонус ещё не был начислен
            # Начисляем бонус для реферера
            referrer["coins"] += 20000  # 20,000 монет
            referrer["normal_case"] += 1  # 1 обычный кейс
            referrer["referral_reward_claimed"] = True  # Помечаем, что бонус был начислен

            # Сохраняем изменения для реферера
            save_user_data(users)

            # Уведомление для реферера
            await bot.send_message(referrer["user_id"], f"🎉 Ваш реферал @{message.from_user.username} достиг уровня 2 и вы получили бонус!")
            print(f"Реферер @{message.from_user.username} получил бонус за достижение уровня 2.")

    return current_level








# Проверка, имеет ли пользователь право на привилегию
def check_privilege_access(user_donate_level, privilege_level):

    try:
        user_level_index = donate_levels_hierarchy.index(user_donate_level)
        privilege_level_index = donate_levels_hierarchy.index(privilege_level)
    except ValueError:
        logging.error("Некорректные уровни доната!")
        return False

    # Если уровень пользователя равен или выше, то доступ разрешен
    if user_level_index >= privilege_level_index:
        return True
    else:
        return False


# Обработка команды /salary
@dp.message_handler(commands=['salary'])
@check_ban
async def salary_command(message: types.Message):
    user_id = message.from_user.id
    user = get_user_data(user_id)
    now = datetime.utcnow()

    if user["banned"]:
        await message.answer("❌ Вы заблокированы в боте.")
        return

    # Проверка, что пользователь уже получил зарплату
    if user.get("last_bonus_time"):
        last_bonus_time = datetime.fromisoformat(user["last_bonus_time"])
        time_since_last_bonus = now - last_bonus_time

        if time_since_last_bonus < timedelta(days=1):
            remaining_time = timedelta(days=1) - time_since_last_bonus
            hours, remainder = divmod(remaining_time.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            await message.answer(
                f"Ты уже получал бонус сегодня. Попробуй снова через {int(hours)}ч {int(minutes)}м {int(seconds)}с."
            )
            return

    # Проверка на наличие VIP статуса и умножение зарплаты на 2, если есть VIP
    salary_multiplier = 2 if user.get("vip", False) else 1

    # Создаем кнопки для выбора привилегий
    keyboard = InlineKeyboardMarkup(row_width=1)
    levels = list(privilege_to_level_map.keys())  # Используем наш словарь для кнопок

    for level in levels:
        button = InlineKeyboardButton(text=level, callback_data=f"salary_{level}")
        keyboard.add(button)

    await message.answer("🔴 Выбери свою привилегию, чтобы получить ежедневную зарплату!", reply_markup=keyboard)

# Обработка выбора привилегии для получения зарплаты
@dp.callback_query_handler(lambda c: c.data.startswith('salary_'))
async def handle_salary_button(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user = get_user_data(user_id)

    # Получаем привилегию, которую выбрал пользователь
    privilege_name = callback_query.data.split('_')[1]
    level = privilege_to_level_map.get(privilege_name)

    if not level:
        await callback_query.answer("❌ Ошибка! Привилегия не существует.")
        return

    # Проверяем, что уровень доната пользователя соответствует привилегии
    user_donate_level = user["donate_level"]

    # Проверяем, имеет ли пользователь доступ к привилегии
    if not check_privilege_access(user_donate_level, level):
        await callback_query.answer(
            f"❌ У вас нет прав на получение этой зарплаты! Требуется уровень доната: {level}.")
        return

    # Проверка, что пользователь еще не получал бонус
    if user.get("last_bonus_time"):
        last_bonus_time = datetime.fromisoformat(user["last_bonus_time"])
        time_since_last_bonus = datetime.utcnow() - last_bonus_time

        if time_since_last_bonus < timedelta(days=1):
            await callback_query.answer("❌ Вы уже получили зарплату сегодня. Попробуйте позже!")
            return

    # Получаем данные привилегии из словаря donation_levels
    privilege_data = donation_levels.get(level)

    if not privilege_data:
        await callback_query.answer("❌ Ошибка! Привилегия не существует.")
        return

    # Выдаем бонус (без учета токенов), учитываем VIP бонус
    bonus_amount = privilege_data.get("bonus", privilege_data["daily_salary"])

    # Если у пользователя VIP, умножаем бонус на 2
    if user.get("vip", False):
        bonus_amount *= 2

    user["coins"] += bonus_amount
    user["last_bonus_time"] = datetime.utcnow().isoformat()

    # Сохраняем данные пользователя
    save_user_data(user)

    try:
        await callback_query.answer(f"⚠️ Поздравляем! Ты получил свою ежедневную зарплату в размере {bonus_amount} 🤑")
    except Exception as e:
        logging.error(f"Ошибка при обработке запроса: {e}")



async def give_level_reward(user_id: int, level: int) -> str:
    global users
    user = get_user_data(user_id)
    reward = level_rewards.get(level)

    if not reward:
        return "Нет наград за этот уровень."

    message = ""
    if "coins" in reward:
        user["coins"] += reward["coins"]
        message += f"+{reward['coins']} монет\n"
    if "tokens" in reward:
        user["tokens"] += reward["tokens"]
        message += f"+{reward['tokens']} токенов\n"
    if "normal_case" in reward:
        user["normal_case"] += reward["normal_case"]
        message += f"+{reward['normal_case']} обычный кейс\n"
    if "big_case" in reward:
        user["big_case"] += reward["big_case"]
        message += f"+{reward['big_case']} большой кейс\n"
    if "mega_case" in reward:
        user["mega_case"] += reward["mega_case"]
        message += f"+{reward['mega_case']} мега кейс\n"
    if "omega_case" in reward:
        user["omega_case"] += reward["omega_case"]
        message += f"+{reward['omega_case']} омега кейс\n"
    if "snow_case" in reward:
        user["snow_case"] += reward["snow_case"]
        message += f"+{reward['snow_case']} снежный кейс\n"
    if "vip_case" in reward:
        user["vip_case"] += reward["vip_case"]
        message += f"+{reward['vip_case']} VIP кейс\n"

    save_user_data(users)  # ✅ исправлено: передаём словарь users
    return "Получены награды:\n" + message



@dp.message_handler(commands=['Event'])
@check_ban
async def event_command(message: types.Message):
    await message.answer("Ссылка на Эвенты: @HyperionLegacy")

# 📌 Команда /Help
@dp.message_handler(commands=['help'])
@check_ban
async def help_command(message: types.Message):
    await message.answer(
        f"<b>❗️Привет @{message.from_user.username}, ты попал в раздел помощи бота <b>Hyperion Legacy</b>. Ниже приведён список всех доступных команд:</b>\n\n"
        "<b>📘Основные команды:</b>\n\n"
        "<blockquote><b>/Erireft</b> — 🎁Получить бонус для хорошего старта\n"
        "<b>/Game</b> — 🕹 Просмотр всех доступных игр\n"
        "<b>/Casino</b> — 🎰 Попробовать удачу в азартной игре\n"
        "<b>/Case</b> — 🎁 Открытие кейсов с призами\n"
        "<b>/Donate</b> — 💎 Информация о донатах и их возможностях\n"
        "<b>/Pay</b> — 💸 Перевод валюты другому игроку\n"
        "<b>/Top</b> — 🏆 Список топ-игроков\n"
        "<b>/Event</b> — 📅 Актуальные ивенты\n"
        "<b>/Tokens</b> — 💰 Подробности о валюте <u>токены</u>\n"
        "<b>/Profile</b> — 📄 Информация о вашем аккаунте\n"
        "<b>/Salary</b> — 📆 Зарплата\n"
        "<b>/Promocode</b> — 🎟 Ввод промокода\n"
        "<b>/Boost</b> — ⚡️ Бусты\n"
        "<b>/Console</b> — 🛠 Админ-панель (доступ только для админов)</blockquote>\n\n"
        "<b>📞Контакты и поддержка:</b>\n\n"
        "<blockquote>🧑‍💻 <b>Поддержка:</b> @LightShock_Fun | @Sashaerireft\n"
        "🛍 <b>Для покупки доната:</b> @Sashaerireft\n"
        "<b>Официальный канал:</b> @HyperionLegacy</blockquote>\n\n"
        "<b>🔧Версия Бота: 1.3.5</b>",
        parse_mode="HTML"
    )


@dp.message_handler(commands=['info'])
@check_ban
async def info_command(message: types.Message):
    user_id = message.from_user.id
    user = get_user_data(user_id)

    donation_level = "Нет"
    for level, details in donation_levels.items():
        if user["tokens"] >= details["tokens"]:
            donation_level = level

    await message.answer(
        f"Привет @{message.from_user.username}!\n"
        f"Твой баланс по монетам: {user['coins']}\n"
        f"Твой баланс по кликам: {user['clicks']}\n"
        f"Твой баланс по токенам: {user['tokens']}\n"
        f"Твой донат: {donation_level}"
    )

@dp.message_handler(commands=['tokens'])
@check_ban
async def tokens_command(message: types.Message):
    await message.answer(
        f"<b>Привет @{message.from_user.username}!\n"
        f"Ты попал в раздел \"Токены\".\n\n"
        "🔹 Что такое токены?\n"
        "Токены используются для оплаты доната, кейсов и других внутриигровых возможностей.\n\n"
        "💰 Курс:\n"
        "1 токен = 1₽\n\n"
        "⚠️ Важно:\n"
        "Покупка токенов осуществляется только через поддержку!\n"
        "❗ Мы не используем никаких ботов или сторонние сервисы для оплаты!\n\n"
        "Хочешь купить токены? Напиши в поддержку → <a href='https://t.me/Sashaerireft'>@Sashaerireft</a></b>"
    , parse_mode="HTML")

# 📌 Профиль
@dp.message_handler(commands=['profile'])
@check_ban
@dp.message_handler(lambda message: message.text.lower() == "профиль")
async def profile_handler(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user_data(user_id)

    # Форматируем дату первого захода
    first_join = user.get("first_join", None)
    if not first_join:
        first_join = datetime.utcnow().isoformat()
        user["first_join"] = first_join
        save_user_data(users)
    first_join_formatted = datetime.fromisoformat(first_join).strftime("%d.%m.%Y %H:%M")

    # Статус доната
    donation_status = user.get("donate_level", "Отсутствует")

    # Статус Gamepass (VIP)
    vip_status = "Активирован" if user.get("vip") else "Отсутствует"

    text = (

        f"@{message.from_user.username}, твой профиль:\n\n"
        f"<blockquote>"
        f"┏🎭 Имя: {message.from_user.first_name or 'Неизвестно'}\n"
        f"┣🆔 Айди: {user_id}\n"
        f"┣🔅 Gamepass: {vip_status}\n"
        f"┣👑 Статус: {donation_status}\n"
        f"┣🧰 Уровень: {user.get('level', 0)}\n" 
        f"┃\n"
        f"┣🛡 Клан: В разработке\n"
        f"┣🏆 Клики: {user.get('clicks', 0)}\n"
        f'┣🔋XP: {user.get("xp", 0)}\n'
        f"┃\n"
        f"┣💎 Токены: {user.get('tokens', 0)}\n"
        f"┣💸 Монеты: {user.get('coins', 0)}\n"
        f"┃\n"
        f"┣👾 Сыграно матчей в КНБ: {user.get('played_rps', 0)}\n"
        f"┣⭐️ Первый раз зашёл в бота: {first_join_formatted}\n"
        f"┗💮 Выиграно Ивентов: В разработке\n\n"
        f"</blockquote>"
        f"💳Купить донат @Sashaerireft"

    )

    await message.answer(text, parse_mode="HTML")




# Обработчик команды /case
@dp.message_handler(commands=['case'])
@check_ban
async def case_commande(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    # Создаем меню с кейсами
    case_menu = InlineKeyboardMarkup()
    case_menu.add(
        InlineKeyboardButton(f"Обычный кейс: {user_data['normal_case']}", callback_data='open_normal_case'),
        InlineKeyboardButton(f"Большой кейс: {user_data['big_case']}", callback_data='open_big_case'),
        InlineKeyboardButton(f"Мега кейс: {user_data['mega_case']}", callback_data='open_mega_case'),
        InlineKeyboardButton(f"Омега кейс: {user_data['omega_case']}", callback_data='open_omega_case')
    )

    # Проверка для VIP кейса (доступен только для Avenger и выше)
    if user_data.get('donate_level') in ['Avenger', 'Titan', 'Darkness', 'D.Helper', 'Helper']:
        case_menu.add(InlineKeyboardButton(f"VIP кейс: {user_data['vip_case']}", callback_data='open_vip_case'))

    # Проверка для Летнего кейса (доступен только для Лето)
    if user_data.get('donate_level') == 'Лето (Сезонный донат)':
        case_menu.add(InlineKeyboardButton(f"Лето кейс: {user_data.get('summer_case', 0)}", callback_data='open_summer_case'))

    case_menu.add(
        InlineKeyboardButton(f"Снежный кейс: {user_data['snow_case']}", callback_data='open_snow_case'),
        InlineKeyboardButton(f"Донат кейс: {user_data.get('donate_case', 0)}", callback_data='open_donate_case')
    )
    case_menu.add(InlineKeyboardButton(">> Купить кейсы", callback_data='show_buy_page'))
    case_menu.add(InlineKeyboardButton("Шансы на выпадение", callback_data='show_case_chances'))

    await message.answer(
        f"💎 Привет {message.from_user.first_name or message.from_user.username}! Выбери кейс, который хочешь открыть:",
        reply_markup=case_menu)



@dp.callback_query_handler(lambda c: c.data.startswith('open_'))
async def open_case_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    case_type = call.data.split('open_')[1]


    # Проверка для донат кейса
    if case_type == "donate_case":
        result = await process_donate_case_action(user_id)
    else:
        result = await process_case_action(user_id, case_type, "open")

    await bot.answer_callback_query(call.id, text=result)
    await bot.send_message(user_id, result)  # Show result
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    await case_command(call.message)  # Send initial menu again

@dp.callback_query_handler(lambda c: c.data == 'show_buy_page')
async def show_buy_page_callback(call: types.CallbackQuery):
    user_id = call.from_user.id

    buy_menu = InlineKeyboardMarkup()
    buy_menu.add(
        InlineKeyboardButton("Купить обычный кейс", callback_data='buy_normal_case'),
        InlineKeyboardButton("Купить большой кейс", callback_data='buy_big_case')
    )
    buy_menu.add(
        InlineKeyboardButton("Купить мега кейс", callback_data='buy_mega_case'),
        InlineKeyboardButton("Купить омега кейс", callback_data='buy_omega_case')
    )
    buy_menu.add(
        InlineKeyboardButton("Купить VIP кейс", callback_data='buy_vip_case'),
        InlineKeyboardButton("Купить снежный кейс", callback_data='buy_snow_case'),
        InlineKeyboardButton("Купить Лето кейс", callback_data='buy_summer_case')

    )
    buy_menu.add(InlineKeyboardButton("<< Назад", callback_data='back_to_main_case_menu'))

    await bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                text="Выберите кейс для покупки:", reply_markup=buy_menu)

# Обработчик для покупки кейсов
@dp.callback_query_handler(lambda c: c.data.startswith('buy_'))
async def buy_case_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    case_type = call.data.split('buy_')[1]

    user_data = get_user_data(user_id)

    # Проверка для покупки VIP кейса
    if case_type == "vip_case" and user_data.get('donate_level') not in ['Avenger', 'Titan', 'Darkness', 'D.Helper', 'Helper']:
        await bot.answer_callback_query(call.id, text="❌ VIP кейс доступен только с донатом Avenger и выше!")
        return

    # Проверка для покупки Летнего кейса
    if case_type == "summer_case" and user_data.get('donate_level') != 'Лето (Сезонный донат)':
        await bot.answer_callback_query(call.id, text="❌ Летний кейс доступен только с донатом Лето!")
        return

    result = await process_case_action(user_id, case_type, "buy")

    await bot.answer_callback_query(call.id, text=result)
    await bot.send_message(user_id, result)  # Показать результат
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    await case_commande(call.message)  # Отправить исходное меню снова


@dp.callback_query_handler(lambda c: c.data == 'back_to_main_case_menu')
async def back_to_main_case_menu_callback(call: types.CallbackQuery):
    await case_command(call.message)

@dp.callback_query_handler(lambda c: c.data == 'show_case_chances')
async def show_case_chances_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    message_text = "Цены кейсов и шансы:\n\n"
    for case_type, price in case_prices.items():
        message_text += f"**{case_type.replace('_', ' ').title()}**: {price} монет\n"
        message_text += "Шансы на выпадение:\n"
        for reward_range, chance in case_rewards[case_type].items():
            message_text += f"  - {reward_range[0]}-{reward_range[1]}: {chance}%\n"
        message_text += "\n"

    await bot.send_message(chat_id=user_id, text=message_text, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)

# Функция обработки донат кейса
# Функция обработки донат кейса
async def process_donate_case_action(user_id):
    user_data = get_user_data(user_id)

    # Проверка на количество донат кейсов
    if user_data['donate_case'] <= 0:
        return "У вас нет донат кейсов для открытия!"

    # Логика для донат кейса: шанс выпадения
    reward = random.choice([  # Пример случайного выбора награды
        {"name": "Авенджер", "duration": random.randint(14, 60), "chance": 76},
        {"name": "Авенджер", "duration": random.randint(90, 180), "chance": 72},
        {"name": "Титан", "duration": random.randint(60, 120), "chance": 67},
        {"name": "Титан", "duration": random.randint(120, 365), "chance": 55},
        {"name": "Даркнесс", "duration": random.randint(30, 90), "chance": 11},
        {"name": "Даркнесс", "duration": float('inf'), "chance": 3}
    ])

    # Уменьшаем количество донат кейсов после открытия
    user_data['donate_case'] -= 1
    save_user_data(users)

    # Формируем результат
    return f"Вы открыли донат кейс и получили: {reward['name']} на {reward['duration']} дней!"




# Создаем меню кейсов с проверками для VIP и Summer кейсов
@dp.message_handler(lambda message: message.text == "Кейсы")
async def case_command(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    # Меню с кейсами
    case_menu = InlineKeyboardMarkup()
    case_menu.add(
        InlineKeyboardButton(f"Обычный кейс: {user_data['normal_case']}", callback_data='open_normal_case'),
        InlineKeyboardButton(f"Большой кейс: {user_data['big_case']}", callback_data='open_big_case'),
        InlineKeyboardButton(f"Мега кейс: {user_data['mega_case']}", callback_data='open_mega_case'),
        InlineKeyboardButton(f"Омега кейс: {user_data['omega_case']}", callback_data='open_omega_case')
    )

    # Проверка для VIP кейса
    if user_data.get('donate_level') == 'Avenger' or user_data.get('donate_level') == 'Titan' or user_data.get('donate_level') == 'Darkness' or user_data.get('donate_level') == 'Helper' or user_data.get('donate_level') == 'D.Helper':
        case_menu.add(InlineKeyboardButton(f"VIP кейс: {user_data['vip_case']}", callback_data='open_vip_case'))

    # Проверка для Летнего кейса
    if user_data.get('donate_level') == 'Лето (Сезонный донат)':
        case_menu.add(InlineKeyboardButton(f"Лето кейс: {user_data.get('summer_case', 0)}", callback_data='open_summer_case'))

    case_menu.add(
        InlineKeyboardButton(f"Снежный кейс: {user_data['snow_case']}", callback_data='open_snow_case'),
        InlineKeyboardButton(f"Донат кейс: {user_data.get('donate_case', 0)}", callback_data='open_donate_case')
    )
    case_menu.add(InlineKeyboardButton("Шансы на выпадение", callback_data='show_case_chances'))

    await message.answer(f"💎 Привет {message.from_user.first_name or message.from_user.username}! Выбери кейс, который хочешь открыть:", reply_markup=case_menu)




@dp.callback_query_handler(lambda c: c.data.startswith('open_'))
async def open_case_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    case_type = call.data.split('open_')[1]

    if case_type == 'donate_case':
        # Открытие донат кейса
        result = await process_donate_case(user_id)
    else:
        # Обработка других кейсов
        result = await process_case_action(user_id, case_type, "open")

    await bot.answer_callback_query(call.id, text=result)
    await bot.send_message(user_id, result)  # Показать результат
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    await case_command(call.message)  # Отправить исходное меню снова


async def process_donate_case(user_id: int) -> str:
    """Функция для открытия донат кейса"""
    user = get_user_data(user_id)

    if user.get('donate_case', 0) <= 0:
        return "❌ У вас нет Донат кейса для открытия."

    # Уменьшаем количество донат кейсов на 1
    user['donate_case'] -= 1
    save_user_data(users)

    # Генерируем случайную награду
    reward = get_donate_case_reward()

    if reward == "Avenger_14_to_60":
        user["donate_level"] = "Avenger"
        user["daily_salary"] = 25000
        user["max_transfers"] = 3
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Avenger' на 14-60 дней!"

    elif reward == "Avenger_90_to_infinity":
        user["donate_level"] = "Avenger"
        user["daily_salary"] = 25000
        user["max_transfers"] = 3
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Avenger' на 90 дней и более!"

    elif reward == "Titan_60_to_120":
        user["donate_level"] = "Titan"
        user["daily_salary"] = 35000
        user["max_transfers"] = 8
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Titan' на 60-120 дней!"

    elif reward == "Titan_120_to_infinity":
        user["donate_level"] = "Titan"
        user["daily_salary"] = 35000
        user["max_transfers"] = 8
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Titan' на 120 дней и более!"

    elif reward == "Darkness_30_to_90":
        user["donate_level"] = "Darkness"
        user["daily_salary"] = 85000
        user["max_transfers"] = 12
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Darkness' на 30-90 дней!"

    elif reward == "Darkness_infinity":
        user["donate_level"] = "Darkness"
        user["daily_salary"] = 85000
        user["max_transfers"] = 12
        user["vip"] = True
        user["vip_case"] = True
        reward_message = "🎉 Вы выиграли донат 'Darkness' навсегда!"

    else:
        reward_message = "❌ К сожалению, вы не выиграли ничего в Донат кейсе."

    # Сохраняем изменения в данных пользователя
    save_user_data(users)

    return reward_message


def get_donate_case_reward():
    """Функция для случайного выбора награды из донат кейса"""
    random_value = random.randint(1, 100)

    DONATE_CASE_CHANCES = {
        "Avenger_14_to_60": 76,  # Шанс для Avenger от 14 до 60 дней
        "Avenger_90_to_infinity": 72,  # Шанс для Avenger от 90 до навсегда
        "Titan_60_to_120": 67,  # Шанс для Titan от 60 до 120 дней
        "Titan_120_to_infinity": 55,  # Шанс для Titan от 120 до навсегда
        "Darkness_30_to_90": 11,  # Шанс для Darkness от 30 до 90 дней
        "Darkness_infinity": 3  # Шанс для Darkness навсегда
    }

    cumulative_chance = 0
    random_value = random.randint(1, 100)

    for reward, chance in DONATE_CASE_CHANCES.items():
        cumulative_chance += chance
        if random_value <= cumulative_chance:
            return reward  # Возвращаем тип доната

    return "No reward"  # В случае если нет выигрыша


@dp.callback_query_handler(lambda c: c.data == 'show_buy_page')
async def show_buy_page_callback(call: types.CallbackQuery):
    user_id = call.from_user.id

    buy_menu = InlineKeyboardMarkup()
    buy_menu.add(
        InlineKeyboardButton("Купить обычный кейс", callback_data='buy_normal_case'),
        InlineKeyboardButton("Купить большой кейс", callback_data='buy_big_case')
    )
    buy_menu.add(
        InlineKeyboardButton("Купить мега кейс", callback_data='buy_mega_case'),
        InlineKeyboardButton("Купить омега кейс", callback_data='buy_omega_case')
    )
    buy_menu.add(
        InlineKeyboardButton("Купить VIP кейс", callback_data='buy_vip_case'),
        InlineKeyboardButton("Купить снежный кейс", callback_data='buy_snow_case')
    )
    buy_menu.add(InlineKeyboardButton("<< Назад", callback_data='back_to_main_case_menu'))

    await bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                text="Выберите кейс для покупки:", reply_markup=buy_menu)


@dp.callback_query_handler(lambda c: c.data.startswith('buy_'))
async def buy_case_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    case_type = call.data.split('buy_')[1]
    result = await process_case_action(user_id, case_type, "buy")

    await bot.answer_callback_query(call.id, text=result)
    await bot.send_message(user_id, result)  # Показать результат
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    await case_command(call.message)


@dp.callback_query_handler(lambda c: c.data == 'back_to_main_case_menu')
async def back_to_main_case_menu_callback(call: types.CallbackQuery):
    await case_command(call.message)


@dp.callback_query_handler(lambda c: c.data == 'show_case_chances')
async def show_case_chances_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    message_text = "Цены кейсов и шансы:\n\n"
    for case_type, price in case_prices.items():
        message_text += f"**{case_type.replace('_', ' ').title()}**: {price} монет\n"
        message_text += "Шансы на выпадение:\n"
        for reward_range, chance in case_rewards[case_type].items():
            message_text += f"  - {reward_range[0]}-{reward_range[1]}: {chance}%\n"
        message_text += "\n"

    await bot.send_message(chat_id=user_id, text=message_text, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)


class CasinoState(StatesGroup):
    waiting_for_bet = State()

casino_chances = {
    2: 30,   # x2
    3: 20,   # x3
    4: 15,   # x4
    5: 9,    # x5
    8: 5,    # x8
    10: 0.1, # x10
    30: 0.1, # x30
    0: 75    # Проигрыш
}





@dp.message_handler(commands=['casino'])
@check_ban
async def casino_command(message: types.Message, state: FSMContext):
    """
    Обработчик команды /casino.  Запускает игру казино, если у пользователя достаточный уровень.
    """
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    if user_data['level'] < 3:
        await message.answer("❌Извините, но у вас нет 3+ уровня!")
        return

    await message.answer(
        f"Привет @{message.from_user.username}! Ты попал в азартную игру \"Казино\".\n"
        "Введи количество монет, которое хочешь поставить (макс. 100.000.000.000)\n"
        "Для выхода из казино введите 'стоп'.\n\n"  # Добавлено объяснение как выйти
        "Шансы:\n"
        "x2: 30%\n"
        "x3: 20%\n"
        "x4: 15%\n"
        "x5: 9%\n"
        "x8: 5%\n"
        "x10: 0.1%\n"
        "x30: 00.1%\n"
        "Проигрыш: 75%"
    )

    await CasinoState.waiting_for_bet.set()
    await state.update_data(user_id=user_id)


@dp.message_handler(state=CasinoState.waiting_for_bet)
async def process_casino_bet(message: types.Message, state: FSMContext):
    """
    Обработчик ставки пользователя. Проверяет ставку, определяет результат игры и обновляет баланс пользователя.
    """
    data = await state.get_data()
    user_id = data.get('user_id')
    user_data = get_user_data(user_id)

    if message.text.lower() == 'стоп':  # Проверка команды выхода
        await message.answer("Вы вышли из казино.")
        await state.finish()
        return


    try:
        bet_amount = int(message.text)
        if not 0 < bet_amount <= 100000000000:
            await message.answer("Пожалуйста, введите сумму ставки в пределах от 1 до 100.000.000.000")
            return
    except ValueError:
        await message.answer("Пожалуйста, введите числовое значение для ставки. Или 'стоп' для выхода.")
        return

    if user_data['coins'] < bet_amount:
        await message.answer("💥Недостаточно монет😶‍🌫️")
        await state.finish() # Завершаем состояние, чтобы можно было начать игру заново.
        return

    # Сначала вычитаем ставку
    user_data['coins'] -= bet_amount

    outcome = random.choices(list(casino_chances.keys()), weights=list(casino_chances.values()), k=1)[0]

    if outcome == 0:  # Loss
        await message.answer("❌К сожалению ты проиграл. Приходи в следующий раз.")
    else:  # Win
        winnings = bet_amount * outcome
        user_data['coins'] += winnings
        await message.answer(f"‼️Ты выиграл {winnings}!")

    users[user_id] = user_data
    save_user_data(users)  # Передаём users
    #await state.finish() # Убрали finish() - чтобы не выходить из состояния.
    # Теперь пользователь останется в состоянии CasinoState.waiting_for_bet и будет ждать следующую ставку








async def fetch_label(user_id: str, bot_id: int) -> str:
    """Возвращает метку для пользователя, если это не бот"""
    try:
        if int(user_id) == bot_id:
            return None  # Не показываем бота
        chat = await bot.get_chat(int(user_id))
        if getattr(chat, "username", None):
            return f"@{chat.username}"
        return f"ID: {user_id}"
    except Exception:
        return "Неизвестный игрок"

def medal(i: int) -> str:

    return ["🥇", "🥈", "🥉"][i] if i < 3 else "🏅"

async def build_message(items, metric_key: str, header: str, unit: str, bot_id: int):

    # Берём TOP_LIMIT пользователей по ключу
    TOP_LIMIT = 10

    # Обработаем элементы, убедившись, что user_data - это словарь
    top = sorted(items, key=lambda x: x[1].get(metric_key, 0) if isinstance(x[1], dict) else 0, reverse=True)[:TOP_LIMIT]

    # Подготовим метки, исключая бота
    final_labels = []
    for user_id, user_data in top:
        label = await fetch_label(user_id, bot_id)
        if label:  # Если метка не None (не бот)
            final_labels.append(label)

    # Сортируем по убыванию значений
    top_sorted = sorted(top, key=lambda x: x[1].get(metric_key, 0) if isinstance(x[1], dict) else 0, reverse=True)[:TOP_LIMIT]

    # Сборка текста
    lines = [header]
    for i, (user_data, lbl) in enumerate(zip(top_sorted, final_labels)):
        value = user_data[1].get(metric_key, 0) if isinstance(user_data[1], dict) else 0
        lines.append(f"{medal(i)} {i + 1} место:\n┣🎭 {lbl}\n┗🏆 {value} {unit}")

    return "\n".join(lines) if len(lines) > 1 else header + "\nПока пусто."


# Команда /top
@dp.message_handler(commands=['top'])
@check_ban
async def top_command(message: types.Message):
    """Отображает топ игроков по монетам, кликам и сыгранным матчам."""
    # Создаём инлайн клавиатуру с кнопками для выбора
    keyboard = InlineKeyboardMarkup(row_width=1)
    button1 = InlineKeyboardButton(text="Топ по Монетам", callback_data="top_coins")
    button2 = InlineKeyboardButton(text="Топ по Кликам", callback_data="top_clicks")
    button3 = InlineKeyboardButton(text="Топ по Сыграным матчам в КНБ", callback_data="top_matches")

    keyboard.add(button1, button2, button3)

    # Отправляем сообщение с клавиатурой
    await message.answer("🔎 Выберите Топ Игроков;", reply_markup=keyboard)


# Обработка выборов топа
@dp.callback_query_handler(lambda c: c.data in ['top_coins', 'top_clicks', 'top_matches'])
async def process_top_selection(callback_query: types.CallbackQuery):
    """Обрабатывает выбор топа и отправляет соответствующее сообщение без повторов, без ID и без бота."""
    TOP_LIMIT = 10
    top_type = callback_query.data

    # ID бота
    bot_id = (await bot.get_me()).id

    # --- выбор типа топа ---
    if top_type == 'top_coins':
        msg = await build_message(users.items(), 'coins', "⚛ Топ-10 игроков по монетам:", "🪙", bot_id)
    elif top_type == 'top_clicks':
        msg = await build_message(users.items(), 'clicks', "💠 Топ-10 игроков по кликам:", "Клики", bot_id)
    else:  # 'top_matches'
        msg = await build_message(users.items(), 'played_rps', "⚽ Топ-10 игроков по сыгранным матчам в КНБ:", "матчей", bot_id)

    await bot.send_message(callback_query.from_user.id, msg)
    await callback_query.answer()




if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
