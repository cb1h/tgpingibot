import logging
from datetime import datetime, timedelta
import ccxt.async_support as ccxt
import aiosqlite
from aiogram import Bot
from config import EXCHANGES, ADMIN_ID, USER_DATA_DB, TOKEN, TRANSACTION_THRESHOLD

# Initialize exchange
exchange = getattr(ccxt, EXCHANGES[0])()

# Initialize bot for sending messages
bot = Bot(token=TOKEN)

def format_large_number(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}b"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}m"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}k"
    else:
        return f"{num:.1f}"

def calculate_percentage_change(new_value, old_value):
    if old_value is None or old_value == 0:
        return "N/A"
    return ((new_value - old_value) / old_value) * 100

async def init_db():
    async with aiosqlite.connect(USER_DATA_DB) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                coins TEXT,
                threshold REAL
            )
        ''')
        await db.commit()

async def load_user_settings():
    user_selections = {}
    user_transaction_thresholds = {}
    async with aiosqlite.connect(USER_DATA_DB) as db:
        async with db.execute('SELECT user_id, coins, threshold FROM user_settings') as cursor:
            async for row in cursor:
                user_id, coins, threshold = row
                user_selections[user_id] = coins.split(',')
                user_transaction_thresholds[user_id] = threshold
    return user_selections, user_transaction_thresholds

async def save_user_settings(user_id, user_selections, user_transaction_thresholds):
    async with aiosqlite.connect(USER_DATA_DB) as db:
        coins = ','.join(user_selections[user_id])
        threshold = user_transaction_thresholds.get(user_id, TRANSACTION_THRESHOLD * 100)
        await db.execute('''
            INSERT OR REPLACE INTO user_settings (user_id, coins, threshold)
            VALUES (?, ?, ?)
        ''', (user_id, coins, threshold))
        await db.commit()

async def fetch_candlestick_volume(coin, since, until, interval='1d'):
    try:
        ohlcv = await exchange.fetch_ohlcv(coin, timeframe=interval, since=since)
        transaction_volume = sum([candle[5] for candle in ohlcv if candle[0] < until])
        return transaction_volume
    except Exception as e:
        logging.error(f"Error fetching candlesticks for {coin}: {e}")
        await bot.send_message(ADMIN_ID, f"Error fetching candlesticks for {coin}: {e}")
        return 0

async def fetch_current_price(coin):
    try:
        ticker = await exchange.fetch_ticker(coin)
        return ticker['last']
    except Exception as e:
        logging.error(f"Error fetching current price for {coin}: {e}")
        await bot.send_message(ADMIN_ID, f"Error fetching current price for {coin}: {e}")
        return None