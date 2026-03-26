FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "discord.py>=2.4" \
    "httpx>=0.27" \
    "python-dotenv>=1.0"

COPY src/signalpro_pricing_strategy/discord_bot.py .

CMD ["python", "-c", "from discord_bot import main; main()"]
