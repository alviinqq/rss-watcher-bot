FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rss_watcher ./rss_watcher
ENV PYTHONUNBUFFERED=1
VOLUME ["/app/data"]
CMD ["python", "-m", "rss_watcher"]
