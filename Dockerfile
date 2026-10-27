# Gulvmåtten til Railway (eller en hvilken som helst Docker-vært).
# Railway sætter PORT. Data (database og den byggede hjemmeside) skal ligge på
# en vedvarende disk; sæt GULVMAATTEN_DATA til diskens sti, fx /data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GULVMAATTEN_DATA=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY gulvmaatten ./gulvmaatten

CMD ["python", "-m", "gulvmaatten", "server"]
