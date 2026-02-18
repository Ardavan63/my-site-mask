FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# نصب FFmpeg جهت پردازش مدیا
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot_core.py .

CMD ["python", "bot_core.py"]
