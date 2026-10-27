from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import sys

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

client = AsyncIOMotorClient(MONGO_URI)
db = client.watchbot

watchlist_collection = db.watchlist
watch_log_collection = db.watch_log
users_collection = db.users


def check_connection():
    """Exit at startup if MongoDB is unreachable, instead of failing on every command later."""
    if not MONGO_URI:
        sys.exit("ERROR: MONGO_URI is not set in .env")
    try:
        # Sync client: the bot's event loop doesn't exist yet, and Motor must stay bound to that loop
        with MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) as sync_client:
            sync_client.admin.command("ping")
    except Exception as e:
        sys.exit(
            f"ERROR: Can't reach MongoDB: {e}\n"
            "Check MONGO_URI in .env (copy a fresh one from Atlas > Connect > Drivers) "
            "and that your IP is allowed under Atlas > Network Access."
        )