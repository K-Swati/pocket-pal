FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pocketpal pocketpal
ENV PORT=8000
CMD uvicorn pocketpal.api:app --host 0.0.0.0 --port ${PORT}
