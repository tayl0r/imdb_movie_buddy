FROM python:3.12-slim

# Logs stream straight to `docker logs` without buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Socket-mode worker: connects out to Slack, no inbound port.
CMD ["python3", "slack_bot.py"]
