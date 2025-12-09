FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY processing_station ./processing_station

EXPOSE 8001
VOLUME ["/app/data"]

CMD ["uvicorn", "processing_station.app:app", "--host", "0.0.0.0", "--port", "8001"]
