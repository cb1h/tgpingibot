from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv('SECRET_TOKEN')
ADMIN_ID = os.getenv('SECRET_ADMIN_ID')
USER_DATA_DB = os.getenv('USER_DATA_DB')

# Thresholds
TRANSACTION_THRESHOLD = 0.1  # 10% of total transactions

# List of exchanges to monitor (now only Binance)
EXCHANGES = ['binance']

# File paths
COINS_FILE = 'coins.txt'
LOG_FILE = 'main.log'