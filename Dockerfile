# Use a lightweight Python base image
FROM python:3.11-slim

# Avoid writing .pyc files and ensure stdout/stderr are unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create a non-root user for running the app
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install Python dependencies first to leverage Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files
COPY . .

USER app

ENV PORT=8080

EXPOSE 8080

# Run the Flask application with Gunicorn in production mode
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--timeout", "120", "app:app"]
