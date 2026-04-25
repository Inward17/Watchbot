from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()

client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client.watchbot

watchlist_collection = db.watchlist
watch_log_collection = db.watch_log
users_collection = db.users