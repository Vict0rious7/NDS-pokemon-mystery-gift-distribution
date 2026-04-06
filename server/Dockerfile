FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Event files are mounted as a read-only volume at runtime (see docker-compose.yml)
# Place .myg files in server/events/gen4/ and .pgf files in server/events/gen5/
RUN mkdir -p /app/events/gen4 /app/events/gen5

EXPOSE 8080

# HTTP/1.0 is required — the DS DLS1 parser rejects HTTP/1.1 responses.
# wsgiref enforces HTTP/1.0 via the custom handler in app.py.
CMD ["python", "-u", "app.py"]