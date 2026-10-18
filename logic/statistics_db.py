import logging

from pymongo import MongoClient
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

class StatisticsManagerDB:
    def __init__(self, mongo_uri):
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.db = self.client.get_database()
            self.history = self.db.history
            self.users = self.db.users

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
        except Exception as e:
            logger.error(f"Error logging decision: {e}", exc_info=True)
            # Don't raise - we don't want to break the game flow if logging fails

    def get_bankroll(self, username):
        # Calculate bankroll for SPECIFIC user
        try:
            stats = self.history.aggregate([
                {"$match": {"username": username}},
                {"$group": {
                    "_id": None,
                    "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                    "total": {"$sum": 1}
                }}
            ])
            res = list(stats)
            if not res: return 10000

            correct = res[0]['correct']
            total = res[0]['total']
            incorrect = total - correct
            starting_bankroll = 10000
            reward_per_correct = 100
            penalty_per_incorrect = 100
            return starting_bankroll + (correct * reward_per_correct) - (incorrect * penalty_per_incorrect)
        except Exception as e:
            logger.error(f"Error calculating bankroll: {e}", exc_info=True)
            return 10000  # Return default on error

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
                    "bankroll": {"$add": [10000, {"$subtract": [{"$multiply": ["$correct", 100]}, {"$multiply": [{"$subtract": ["$total", "$correct"]}, 100]}]}]},
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
            logger.info(f"Cleared {result.deleted_count} records for user: {username}")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error clearing stats: {e}", exc_info=True)
            raise
