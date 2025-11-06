# lambda_function.py
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("WATCHLIST_TABLE", "MovieWatchlist")
table = dynamodb.Table(TABLE_NAME)

def simple_sentiment(text: str) -> str:
    if not text:
        return "NEUTRAL"
    t = text.lower()
    positive = ["good","great","amazing","fantastic","loved","wonderful","awesome","excellent","like"]
    negative = ["bad","terrible","awful","boring","hate","hated","worst","disappointing"]
    pos = sum(1 for w in positive if w in t)
    neg = sum(1 for w in negative if w in t)
    if pos > neg:
        return "POSITIVE"
    if neg > pos:
        return "NEGATIVE"
    return "NEUTRAL"

def build_response(status_code, body_obj):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET"
        },
        "body": json.dumps(body_obj)
    }

def parse_event_body(event):
    # Accept both API Gateway proxy (event['body'] string) and direct invocation (dict)
    raw = event.get("body", event)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            # raw might be a plain string
            try:
                return json.loads(raw.strip('"'))
            except Exception:
                return {"raw": raw}
    elif isinstance(raw, dict):
        return raw
    else:
        return {}

def lambda_handler(event, context):
    try:
        body = parse_event_body(event)
        action = body.get("action", "analyze")
        username = body.get("username", "guest")
        movie = body.get("movie")
        review = body.get("review", "")

        if action == "analyze":
            sentiment = simple_sentiment(review)
            # Save basic record to DynamoDB (optional)
            try:
                table.put_item(Item={
                    "username": username,
                    "movie": movie or "Unknown",
                    "review": review or "",
                    "sentiment": sentiment
                })
            except Exception as e:
                # non-fatal: continue but log it
                print("DDB put_item failed:", str(e))

            recs = {
                "POSITIVE": ["Inception","The Dark Knight","Interstellar"],
                "NEGATIVE": ["Inside Out","Good Will Hunting","The Pursuit of Happyness"],
                "NEUTRAL": ["Forrest Gump","Cast Away","The Matrix"]
            }
            return build_response(200, {
                "message": "Analysis complete",
                "sentiment": sentiment,
                "recommendations": recs.get(sentiment, [])
            })

        elif action == "add":
            if not movie:
                return build_response(400, {"error": "movie required for add"})
            table.put_item(Item={"username": username, "movie": movie})
            return build_response(200, {"message": f"Added {movie} to {username}'s watchlist"})

        elif action == "view":
            resp = table.query(KeyConditionExpression=Key("username").eq(username))
            movies = [item["movie"] for item in resp.get("Items", [])]
            return build_response(200, {"watchlist": movies})

        else:
            return build_response(400, {"error": "invalid action"})

    except Exception as e:
        print("ERROR:", str(e))
        return build_response(500, {"error": str(e)})
