import boto3
import json
import os

comprehend = boto3.client("comprehend")
dynamodb = boto3.resource("dynamodb")

# DynamoDB table
TABLE_NAME = os.environ.get("WATCHLIST_TABLE", "MovieWatchlist")
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    try:
        body = json.loads(event["body"])

        action = body.get("action", "analyze")
        username = body.get("username", "guest")

        if action == "analyze":
            review = body["review"]
            movie = body.get("movie", "Unknown")

            sentiment = comprehend.detect_sentiment(Text=review, LanguageCode="en")["Sentiment"]

            # Save review + sentiment
            table.put_item(Item={
                "username": username,
                "movie": movie,
                "review": review,
                "sentiment": sentiment
            })

            # For demo, fake recommendations
            recs = {
                "POSITIVE": ["The Dark Knight", "Inception", "Interstellar"],
                "NEGATIVE": ["The Room", "Cats"],
                "NEUTRAL": ["Forrest Gump", "Cast Away"],
                "MIXED": ["Joker", "Fight Club"]
            }

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "sentiment": sentiment,
                    "recommendations": recs.get(sentiment, [])
                })
            }

        elif action == "add":
            movie = body["movie"]
            table.put_item(Item={
                "username": username,
                "movie": movie
            })
            return {
                "statusCode": 200,
                "body": json.dumps({"message": f"{movie} added to {username}'s watchlist"})
            }

        elif action == "view":
            resp = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("username").eq(username)
            )
            movies = [item["movie"] for item in resp.get("Items", [])]
            return {
                "statusCode": 200,
                "body": json.dumps({"watchlist": movies})
            }

        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid action"})
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
