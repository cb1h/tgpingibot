import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    TRANSACTION_THRESHOLD, EXCHANGES,
    COINS_FILE, LOG_FILE, TOKEN, ADMIN_ID
)
from utils import (
    format_large_number, calculate_percentage_change,
    init_db, load_user_settings, save_user_settings,
    fetch_candlestick_volume, fetch_current_price
)
import ccxt.async_support as ccxt

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

bot = Bot(token=TOKEN)

# Initialize storage dispatcher
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Initialize exchange
exchange = getattr(ccxt, EXCHANGES[0])()

# Read cryptocurrencies from coins.txt
try:
    with open(COINS_FILE, 'r') as f:
        CRYPTOCURRENCIES = [line.strip().strip("'").strip(",") for line in f if line.strip().startswith("'")]
except FileNotFoundError:
    logging.error(f"File {COINS_FILE} not found. Please ensure the file exists.")
    raise SystemExit(f"File {COINS_FILE} not found. Please ensure the file exists.")

# Remove trailing apostrophes from each coin
CRYPTOCURRENCIES = [coin.rstrip("'") for coin in CRYPTOCURRENCIES]

# Log the cryptocurrencies read from coins.txt
logging.info(f"Cryptocurrencies read from coins.txt: {CRYPTOCURRENCIES}")

# Check if CRYPTOCURRENCIES is empty
if not CRYPTOCURRENCIES:
    logging.error("No cryptocurrencies found in coins.txt. Please ensure the file is not empty and contains valid data.")
    raise SystemExit("No cryptocurrencies found in coins.txt. Please ensure the file is not empty and contains valid data.")

# Default cryptocurrencies to monitor
DEFAULT_CRYPTOCURRENCIES = ['BTC/USDT', 'ETH/USDT', 'DOGE/USDT']

# Store previous data
previous_data = {coin: {'transactions': None, 'transactions_24h': None} for coin in CRYPTOCURRENCIES}

# Store user selections
user_selections = {}

# Store user-defined transaction thresholds
user_transaction_thresholds = {}

# Cache for fetched data
data_cache = {}

async def update_cache():
    while True:
        for coin in CRYPTOCURRENCIES:
            try:
                now = datetime.now(timezone.utc)
                data_cache[coin] = {
                    'transactions': await fetch_candlestick_volume(coin, 0, int((now - timedelta(hours=24)).timestamp() * 1000)),
                    'transactions_24h': await fetch_candlestick_volume(coin, int((now - timedelta(hours=24)).timestamp() * 1000), int(now.timestamp() * 1000)),
                    'current_price': await fetch_current_price(coin)
                }
            except Exception as e:
                logging.error(f"Error updating cache for {coin}: {e}")
                await bot.send_message(ADMIN_ID, f"Error updating cache for {coin}: {e}")
        await asyncio.sleep(180)  # Update cache every 3 minutes

async def check_transactions():
    while True:
        for coin in CRYPTOCURRENCIES:
            try:
                if coin not in data_cache:
                    logging.error(f"Coin {coin} not found in data_cache")
                    continue

                transactions_24h = data_cache[coin]['transactions_24h']
                total_transaction_volume = data_cache[coin]['transactions']

                for user_id, selected_coins in user_selections.items():
                    if coin in selected_coins:
                        # Calculate percentage changes
                        transaction_percentage_change = calculate_percentage_change(transactions_24h, previous_data[coin]['transactions'])

                        # Check for significant increase in transactions
                        if transaction_percentage_change != "N/A" and transaction_percentage_change > user_transaction_thresholds.get(user_id, TRANSACTION_THRESHOLD * 100):
                            message = (
                                f"Significant increase in transactions for {coin}: "
                                f"{transaction_percentage_change:.2f}%"
                            )
                            try:
                                await bot.send_message(user_id, message)
                            except Exception as e:
                                logging.error(f"Failed to send message to {user_id}: {e}")
                                await bot.send_message(ADMIN_ID, f"Failed to send message to {user_id}: {e}")

                        # Update previous data
                        previous_data[coin]['transactions'] = total_transaction_volume
                        previous_data[coin]['transactions_24h'] = transactions_24h
            except KeyError as e:
                logging.error(f"Error checking transactions for {coin}: {e}")
                await bot.send_message(ADMIN_ID, f"Error checking transactions for {coin}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error checking transactions for {coin}: {e}")
                await bot.send_message(ADMIN_ID, f"Unexpected error checking transactions for {coin}: {e}")

        await asyncio.sleep(60)  # Check every minute

async def monitor_api():
    while True:
        try:
            await exchange.fetch_status()
        except Exception as e:
            logging.error(f"API status check failed: {e}")
            await bot.send_message(ADMIN_ID, f"API status check failed: {e}")
        await asyncio.sleep(300)  # Check API status every 5 minutes

@dp.message(Command('start'))
async def start_command(msg: Message):
    user_id = msg.from_user.id
    if user_id not in user_selections:
        user_selections[user_id] = DEFAULT_CRYPTOCURRENCIES.copy()
        user_transaction_thresholds[user_id] = TRANSACTION_THRESHOLD * 100
        await save_user_settings(user_id, user_selections, user_transaction_thresholds)
    await msg.answer(
        "Hello! This bot monitors cryptocurrency transactions.\n"
        "Use /status to get the current status of monitored cryptocurrencies.\n"
        "Use /set_threshold <percentage> to set the transaction threshold for notifications.\n"
        "Use /get_coins to get the list of available cryptocurrencies for monitoring.\n"
        "Use /set_coins <coin> to add or remove a cryptocurrency from monitoring.\n"
        "Use /settings to view your current settings.\n"
        "For any questions or support, please contact the admin."
    )

@dp.message(Command('status'))
async def status_command(msg: Message):
    user_id = msg.from_user.id
    selected_coins = user_selections.get(user_id, DEFAULT_CRYPTOCURRENCIES)
    now = datetime.now(timezone.utc)
    status_message = "Current status of monitored cryptocurrencies:\n"
    messages = []

    for coin in selected_coins:
        try:
            daily_volumes = []
            for i in range(10):
                since = int((now - timedelta(days=i+1)).timestamp() * 1000)
                until = int((now - timedelta(days=i)).timestamp() * 1000)
                volume = await fetch_candlestick_volume(coin, since, until)
                daily_volumes.append(volume)

            transaction_percentage_changes = [
                calculate_percentage_change(daily_volumes[i], daily_volumes[i+1])
                for i in range(9)
            ]

            status_message += f"{coin}:\n"
            for i in range(9):
                day_i = (now - timedelta(days=i)).strftime('%Y-%m-%d')
                day_i_plus_1 = (now - timedelta(days=i+1)).strftime('%Y-%m-%d')
                status_message += f"From {day_i_plus_1} to {day_i}:\n"
                status_message += f"  Transactions Volume Change: {transaction_percentage_changes[i]:.2f}%\n"

            # Calculate volumes for the last 24 hours and the previous 24 hours
            transactions_24h = data_cache[coin]['transactions_24h']
            transactions_48h = await fetch_candlestick_volume(coin, int((now - timedelta(hours=48)).timestamp() * 1000), int((now - timedelta(hours=24)).timestamp() * 1000), interval='1h')
            transaction_percentage_change_24h = calculate_percentage_change(transactions_24h, transactions_48h)
            current_price = data_cache[coin]['current_price']

            if current_price is None:
                raise ValueError(f"Current price for {coin} is None")

            status_message += "\nPercentage changes for the last 24 hours:\n"
            status_message += f"{coin} Transactions Volume Change: {transaction_percentage_change_24h:.2f}%\n"
            status_message += f"Current Price: ${current_price}\n\n"

            if len(status_message) > 4000:  # Telegram message limit
                messages.append(status_message)
                status_message = "Current status of monitored cryptocurrencies:\n"
        except KeyError as e:
            logging.error(f"Error generating status for {coin}: {e}")
            await bot.send_message(ADMIN_ID, f"Error generating status for {coin}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error generating status for {coin}: {e}")
            await bot.send_message(ADMIN_ID, f"Unexpected error generating status for {coin}: {e}")

    if status_message:
        messages.append(status_message)
    for message in messages:
        await msg.answer(message)

@dp.message(Command('set_threshold'))
async def set_threshold_command(msg: Message):
    user_id = msg.from_user.id
    try:
        threshold = float(msg.text.split()[1])
        if 0 <= threshold <= 100:
            user_transaction_thresholds[user_id] = threshold
            await save_user_settings(user_id, user_selections, user_transaction_thresholds)
            await msg.answer(f"Transaction threshold set to {threshold}%.")
        else:
            await msg.answer("Please provide a valid percentage between 0 and 100.")
    except (IndexError, ValueError) as e:
        await msg.answer("Usage: /set_threshold <percentage>")
        await bot.send_message(ADMIN_ID, f"Error in set_threshold_command: {e}")

@dp.message(Command('get_coins'))
async def get_coins_command(msg: Message):
    try:
        coins_list = "\n".join(CRYPTOCURRENCIES)
        await msg.answer(f"Here is the list of available cryptocurrencies:\n{coins_list}\n\nUse /set_coins <coin> to add or remove a cryptocurrency from monitoring.")
    except Exception as e:
        logging.error(f"Error in get_coins_command: {e}")
        await bot.send_message(ADMIN_ID, f"Error in get_coins_command: {e}")

@dp.message(Command('set_coins'))
async def set_coins_command(msg: Message):
    user_id = msg.from_user.id
    if user_id not in user_selections:
        user_selections[user_id] = DEFAULT_CRYPTOCURRENCIES.copy()
    try:
        coin = msg.text.split()[1].upper()
        if coin not in CRYPTOCURRENCIES:
            await msg.answer(f"The coin {coin} is not valid. Please use /get_coins to see the list of available cryptocurrencies.")
            return

        if coin in user_selections[user_id]:
            user_selections[user_id].remove(coin)
            action = "removed from"
        else:
            user_selections[user_id].append(coin)
            action = "added to"

        await save_user_settings(user_id, user_selections, user_transaction_thresholds)
        await msg.answer(f"The coin {coin} has been {action} your selection.\nCurrent selection: {', '.join(user_selections[user_id])}")
    except IndexError as e:
        await msg.answer("Usage: /set_coins <coin>")
        await bot.send_message(ADMIN_ID, f"Error in set_coins_command: {e}")

@dp.message(Command('settings'))
async def settings_command(msg: Message):
    try:
        user_id = msg.from_user.id
        selected_coins = user_selections.get(user_id, DEFAULT_CRYPTOCURRENCIES)
        threshold = user_transaction_thresholds.get(user_id, TRANSACTION_THRESHOLD * 100)
        settings_message = (
            f"Your current settings:\n"
            f"Monitored coins: {', '.join(selected_coins)}\n"
            f"Transaction threshold for notifications: {threshold}%"
        )
        await msg.answer(settings_message)
    except Exception as e:
        logging.error(f"Error in settings_command: {e}")
        await bot.send_message(ADMIN_ID, f"Error in settings_command: {e}")

@dp.message(Command('help'))
async def help_command(msg: Message):
    try:
        help_message = (
            "Here are the available commands:\n"
            "/start - Start the bot and get a welcome message.\n"
            "/status - Get the current status of monitored cryptocurrencies.\n"
            "/set_threshold <percentage> - Set the transaction threshold for notifications.\n"
            "/get_coins - Get the list of available cryptocurrencies for monitoring.\n"
            "/set_coins <coin> - Add or remove a cryptocurrency from monitoring.\n"
            "/settings - View your current settings.\n"
            "\nFor any questions or support, please contact the admin."
        )
        await msg.answer(help_message)
    except Exception as e:
        logging.error(f"Error in help_command: {e}")
        await bot.send_message(ADMIN_ID, f"Error in help_command: {e}")

async def main():
    await init_db()
    global user_selections, user_transaction_thresholds
    user_selections, user_transaction_thresholds = await load_user_settings()
    asyncio.create_task(update_cache())
    asyncio.create_task(check_transactions())
    asyncio.create_task(monitor_api())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())