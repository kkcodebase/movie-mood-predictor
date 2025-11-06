@echo off
echo Packaging Lambda function...
powershell -Command "Compress-Archive -Path sentiment_handler.py -DestinationPath function.zip -Force"

echo Deploying Lambda to AWS...
aws lambda update-function-code --function-name MovieSentimentHandler --zip-file fileb://function.zip --region us-east-1

echo Done! 
pause
