import logging

from pymongo import MongoClient
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

# --- Scoring ---
# These were duplicated in app.py and again inside the leaderboard aggregation,
# so changing one left the HUD and the leaderboard disagreeing.
STARTING_BANKROLL = 10000
CORRECT_REWARD = 100
INCORRECT_PENALTY = 100


def bankroll_from(correct: int, total: int) -> int:
    """The one definition of what a bankroll is."""
    return STARTING_BANKROLL + correct * CORRECT_REWARD - (total - correct) * INCORRECT_PENALTY

class StatisticsManagerDB:
    def __init__(self, mongo_uri):
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.db = self.client.get_database()
            self.history = self.db.history
            self.users = self.db.users
            #: Running per-user counts, so a bankroll is a point read rather
            #: than an aggregation over the user's whole history on every hand.
            self.totals = self.db.totals

            # Create indexes for better query performance
            self._create_indexes()
            logger.info("MongoDB connection established and indexes created")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}", exc_info=True)
            raise

    def _create_indexes(self):
        """Create database indexes for frequently queried fields"""
        try:
            # Index on username for user-specific queries
            self.history.create_index("username")
            # Compound index for username + is_correct for faster aggregations
            self.history.create_index([("username", 1), ("is_correct", 1)])
            # Index on username for users collection
            self.users.create_index("username", unique=True)
            # Running totals, one document per user.
            self.totals.create_index("username", unique=True)
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.warning(f"Error creating indexes (may already exist): {e}")

    # --- USER AUTHENTICATION ---
    def create_user(self, username, password):
        try:
            if self.users.find_one({"username": username}):
                return False # User exists

            self.users.insert_one({
                "username": username,
                "password": generate_password_hash(password)
            })
            logger.info(f"User created: {username}")
            return True
        except Exception as e:
            logger.error(f"Error creating user: {e}", exc_info=True)
            return False

    def verify_user(self, username, password):
        try:
            user = self.users.find_one({"username": username})
            if not user:
                return False
            return check_password_hash(user["password"], password)
        except Exception as e:
            logger.error(f"Error verifying user: {e}", exc_info=True)
            return False

    # --- HISTORY (Scoped to User) ---
    def log_decision(self, result, username):
        try:
            entry = {
                "username": username, # <-- NEW: Link entry to user
                "is_correct": result.is_correct,
                "hero_position": result.scenario.hero_position.value,
                "stack": result.scenario.effective_stack_bb,
                "hand": result.scenario.hero_hand.range_notation,
                "action": result.user_action.value,
                "correct": result.correct_action.value,
                "chart": result.scenario.chart_key
            }
            self.history.insert_one(entry)
            self.totals.update_one(
                {"username": username},
                {"$inc": {"total": 1, "correct": 1 if result.is_correct else 0}},
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Error logging decision: {e}", exc_info=True)
            # Don't raise - we don't want to break the game flow if logging fails

    def get_bankroll(self, username):
        """
        Read the user's running totals.

        This used to aggregate the user's entire history on every single hand,
        which is O(hands played) per decision.
        """
        try:
            totals = self.totals.find_one({"username": username})
            if not totals:
                totals = self._backfill_totals(username)
            return bankroll_from(totals.get("correct", 0), totals.get("total", 0))
        except Exception as e:
            logger.error(f"Error calculating bankroll: {e}", exc_info=True)
            return STARTING_BANKROLL

    def _backfill_totals(self, username):
        """
        Build a user's running totals from their history.

        Needed once per user for data written before totals existed, otherwise
        their bankroll would read as the starting amount while the leaderboard,
        which counts history directly, showed the real figure.
        """
        counts = list(self.history.aggregate([
            {"$match": {"username": username}},
            {"$group": {
                "_id": None,
                "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                "total": {"$sum": 1},
            }},
        ]))
        totals = {"correct": counts[0]["correct"], "total": counts[0]["total"]} if counts else {
            "correct": 0, "total": 0
        }
        if totals["total"]:
            self.totals.update_one({"username": username}, {"$set": totals}, upsert=True)
            logger.info("Backfilled totals for %s from %d history records", username, totals["total"])
        return totals

    def get_leaderboard(self, limit=10):
        """
        Calculates bankroll for ALL users and returns top 10.
        Note: In a massive app, we'd cache this. For now, aggregation is fine.
        """
        try:
            pipeline = [
                {"$group": {
                    "_id": "$username",
                    "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                    "total": {"$sum": 1}
                }},
                {"$project": {
                    "username": "$_id",
                    "bankroll": {"$add": [
                        STARTING_BANKROLL,
                        {"$subtract": [
                            {"$multiply": ["$correct", CORRECT_REWARD]},
                            {"$multiply": [{"$subtract": ["$total", "$correct"]}, INCORRECT_PENALTY]},
                        ]},
                    ]},
                    "hands": "$total",
                    "accuracy": {"$cond": [{"$eq": ["$total", 0]}, 0, {"$multiply": [{"$divide": ["$correct", "$total"]}, 100]}]}
                }},
                {"$sort": {"bankroll": -1}},
                {"$limit": limit}
            ]
            return list(self.history.aggregate(pipeline))
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}", exc_info=True)
            return []

    def get_overall_accuracy(self, username):
        try:
            match = {"username": username}
            total = self.history.count_documents(match)
            if total == 0: return {"correct": 0, "total": 0, "percent": 0.0}
            correct = self.history.count_documents({**match, "is_correct": True})
            return {"correct": correct, "total": total, "percent": (correct/total)*100}
        except Exception as e:
            logger.error(f"Error getting overall accuracy: {e}", exc_info=True)
            return {"correct": 0, "total": 0, "percent": 0.0}

    def get_accuracy_by_position(self, username):
        try:
            pipeline = [
                {"$match": {"username": username}},
                {"$group": {
                    "_id": "$hero_position",
                    "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                    "total": {"$sum": 1}
                }}
            ]
            return self._process_aggregation(pipeline)
        except Exception as e:
            logger.error(f"Error getting accuracy by position: {e}", exc_info=True)
            return {}

    def get_accuracy_by_stack(self, username):
        try:
            pipeline = [
                {"$match": {"username": username}},
                {"$group": {
                    "_id": "$stack",
                    "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                    "total": {"$sum": 1}
                }}
            ]
            return self._process_aggregation(pipeline)
        except Exception as e:
            logger.error(f"Error getting accuracy by stack: {e}", exc_info=True)
            return {}

    def get_recent_history(self, username, limit=50):
        try:
            cursor = self.history.find({"username": username}).sort("_id", -1).limit(limit)
            results = []
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                results.append(doc)
            return results
        except Exception as e:
            logger.error(f"Error getting recent history: {e}", exc_info=True)
            return []

    def _process_aggregation(self, pipeline):
        try:
            results = {}
            cursor = self.history.aggregate(pipeline)
            for doc in cursor:
                key = str(doc["_id"])
                total = doc["total"]
                correct = doc["correct"]
                percent = (correct / total) * 100 if total > 0 else 0.0
                results[key] = {
                    "correct": correct,
                    "total": total,
                    "percent": percent
                }
            return results
        except Exception as e:
            logger.error(f"Error processing aggregation: {e}", exc_info=True)
            return {}

    def clear_stats(self, username):
        try:
            result = self.history.delete_many({"username": username})
            self.totals.delete_one({"username": username})
            logger.info(f"Cleared {result.deleted_count} records for user: {username}")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error clearing stats: {e}", exc_info=True)
            raise
