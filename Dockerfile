FROM python:3.12-slim

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application
COPY cortivium/ cortivium/
COPY migrations/ migrations/
COPY server.py .
COPY .env.example .

# Create storage directory
RUN mkdir -p /app/storage

# Expose port
EXPOSE 8080

# Volume for persistent data (database + runtime files)
VOLUME ["/app/storage"]

CMD ["python", "server.py"]
