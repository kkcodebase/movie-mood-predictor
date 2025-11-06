import os
import json
import random
import uuid
import datetime
import logging

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Config (can override with Lambda environment variables)
WATCHLIST_TABLE = os.environ.get("WATCHLIST_TABLE", "MoodPlayWatchlist")
REVIEWS_TABLE = os.environ.get("REVIEWS_TABLE", "MoodPlayReviews")

# AWS clients/resources
dynamodb = boto3.resource("dynamodb")
# optional: Comprehend if available (we'll try/catch)
comprehend = boto3.client("comprehend")

# Movies metadata (unchanged)
MOVIE_METADATA = [
    {"title": "Forrest Gump", "moods": ["happy", "relaxed"], "sentiments": ["positive", "neutral"]},
    {"title": "The Intouchables", "moods": ["happy", "relaxed"], "sentiments": ["positive"]},
    {"title": "Guardians of the Galaxy", "moods": ["happy"], "sentiments": ["positive"]},
    {"title": "La La Land", "moods": ["happy", "relaxed"], "sentiments": ["positive"]},
    {"title": "Schindler's List", "moods": ["sad"], "sentiments": ["negative"]},
    {"title": "The Pursuit of Happyness", "moods": ["sad", "happy"], "sentiments": ["positive", "negative"]},
    {"title": "Lost in Translation", "moods": ["relaxed"], "sentiments": ["neutral"]},
    {"title": "Amélie", "moods": ["relaxed", "happy"], "sentiments": ["positive"]},
    {"title": "The Notebook", "moods": ["sad"], "sentiments": ["negative", "positive"]},
    {"title": "Titanic", "moods": ["sad"], "sentiments": ["negative"]},
    {"title": "Up", "moods": ["happy"], "sentiments": ["positive"]},
    {"title": "Inside Out", "moods": ["happy", "relaxed"], "sentiments": ["positive", "neutral"]},
    {"title": "Blue Valentine", "moods": ["sad"], "sentiments": ["negative"]},
    {"title": "Pride & Prejudice", "moods": ["relaxed"], "sentiments": ["neutral", "positive"]},
    {"title": "Moonrise Kingdom", "moods": ["relaxed", "happy"], "sentiments": ["positive"]},
    {"title": "Chef", "moods": ["happy", "relaxed"], "sentiments": ["positive"]}
]

# In-memory backup store (used if DynamoDB is not available)
USER_WATCHLISTS = {}

# --- Helper responses ---
def response_ok(payload):
    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps(payload)
    }

def response_error(msg, code=500):
    return {
        "statusCode": code,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"error": msg})
    }

# --- DynamoDB helpers (safe: fall back if table missing / permissions) ---
def get_watchlist_db(username):
    try:
        table = dynamodb.Table(WATCHLIST_TABLE)
        resp = table.query(KeyConditionExpression=Key('username').eq(username))
        items = resp.get('Items', [])
        return [item['movie'] for item in items]
    except Exception as e:
        logger.warning("DynamoDB get_watchlist failed: %s", e)
        return None  # caller will fallback to memory

def add_to_watchlist_db(username, movie):
    try:
        table = dynamodb.Table(WATCHLIST_TABLE)
        # Put item with PK username and SK movie
        table.put_item(Item={
            "username": username,
            "movie": movie,
            "added_at": datetime.datetime.utcnow().isoformat()
        })
        return True
    except Exception as e:
        logger.warning("DynamoDB add_to_watchlist failed: %s", e)
        return False

def save_review_db(username, movie, review, sentiment, sentiment_scores):
    try:
        table = dynamodb.Table(REVIEWS_TABLE)
        review_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow().isoformat()
        item = {
            "username": username,
            "review_id": review_id,
            "movie": movie,
            "review": review,
            "sentiment": sentiment,
            "sentiment_scores": sentiment_scores or {},
            "created_at": created_at
        }
        table.put_item(Item=item)
        return review_id
    except Exception as e:
        logger.warning("DynamoDB save_review failed: %s", e)
        return None

# --- Simple fallback sentiment (keyword-based) ---
def fallback_keyword_sentiment(review):
    positives = ["good", "great", "awesome", "amazing", "love", "excellent", "wonderful", "funny", "hilarious"]
    negatives = ["bad", "boring", "worst", "hate", "awful", "poor", "terrible", "waste"]
    sentiment = "neutral"
    rl = (review or "").lower()
    if any(w in rl for w in positives):
        sentiment = "positive"
    elif any(w in rl for w in negatives):
        sentiment = "negative"
    return sentiment, {}

# --- Attempt Comprehend, but safe fallback ---
def analyze_with_comprehend_safe(review):
    try:
        resp = comprehend.detect_sentiment(Text=review, LanguageCode='en')
        sentiment = (resp.get("Sentiment") or "NEUTRAL").lower()
        scores = resp.get("SentimentScore", {})
        # convert to percentages for storage/display
        scores_pct = {k.lower(): round(float(v) * 100, 2) for k, v in scores.items()}
        return sentiment, scores_pct
    except Exception as e:
        logger.info("Comprehend not available or failed: %s", e)
        return fallback_keyword_sentiment(review)

# --- Personalized suggestions (same logic you approved) ---
def suggest_personalized(movie, sentiment):
    movie_info = next((m for m in MOVIE_METADATA if m["title"].lower() == movie.lower()), None)
    if not movie_info:
        return []
    reviewed_moods = movie_info["moods"]

    if sentiment == "positive":
        candidates = [m for m in MOVIE_METADATA if any(mood in m["moods"] for mood in reviewed_moods)]
    elif sentiment == "negative":
        candidates = [m for m in MOVIE_METADATA if all(mood not in m["moods"] for mood in reviewed_moods)]
    else:
        candidates = MOVIE_METADATA

    return random.sample(candidates, min(5, len(candidates)))

# --- Lambda entrypoint ---
def lambda_handler(event, context):
    try:
        body = event.get("body", "{}")
        if isinstance(body, str):
            body = json.loads(body)

        username = body.get("username", "guest")
        movie = body.get("movie", "")
        review = body.get("review", "")
        action = body.get("action", "analyze")
        mood = (body.get("mood") or "").lower()

        # ensure user exists in in-memory store for fallback
        if username not in USER_WATCHLISTS:
            USER_WATCHLISTS[username] = []

        # === view watchlist ===
        if action == "view":
            watchlist = get_watchlist_db(username)
            if watchlist is None:
                # fallback to in-memory
                watchlist = USER_WATCHLISTS.get(username, [])
            return response_ok({"watchlist": watchlist})

        # === add movie to watchlist ===
        if action == "add" and movie:
            success = add_to_watchlist_db(username, movie)
            if not success:
                # fallback to in-memory
                if movie not in USER_WATCHLISTS[username]:
                    USER_WATCHLISTS[username].append(movie)
            # return updated watchlist (try DB first)
            watchlist = get_watchlist_db(username)
            if watchlist is None:
                watchlist = USER_WATCHLISTS.get(username, [])
            return response_ok({"watchlist": watchlist})

        # === suggest movies based on mood (unchanged) ===
        if action == "suggest" and mood:
            filtered_movies = [m for m in MOVIE_METADATA if mood in m["moods"]]
            suggestions = random.sample(filtered_movies, min(8, len(filtered_movies)))
            return response_ok({"suggestions": suggestions})

        # === analyze (default) ===
        if not review:
            sentiment = "neutral"
            sentiment_scores = {}
            saved_review_id = None
            saved_ok = False
        else:
            # try Comprehend then fallback
            sentiment, sentiment_scores = analyze_with_comprehend_safe(review)
            # Save review to DynamoDB (best-effort)
            saved_review_id = save_review_db(username, movie, review, sentiment, sentiment_scores)
            saved_ok = saved_review_id is not None

        # personalized suggestions based on the reviewed movie + sentiment
        personalized_suggestions = []
        if movie and review:
            personalized_suggestions = suggest_personalized(movie, sentiment)

        response = {
            "username": username,
            "movie": movie,
            "sentiment": sentiment,
            "sentiment_scores": sentiment_scores,
            "message": f"Your review of '{movie}' seems {sentiment}!",
            "personalized_suggestions": personalized_suggestions,
            "saved_review": saved_ok,
            "review_id": saved_review_id
        }
        return response_ok(response)

    except Exception as e:
        logger.exception("Unhandled error in lambda_handler")
        return response_error(str(e))
