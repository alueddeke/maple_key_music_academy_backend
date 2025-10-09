# Django Backend Dockerfile for Maple Key Music Academy
# Optimized for development with PostgreSQL support

# DEV

# FROM python:3.11-bookworm

# # Set environment variables
# ENV PYTHONUNBUFFERED 1
# ENV DEBIAN_FRONTEND=noninteractive

# # Install system dependencies
# RUN apt-get -y update && apt-get -y upgrade
# RUN apt-get -y install \
#     postgresql \
#     postgresql-contrib \
#     build-essential \
#     libpq-dev

# # Set working directory
# WORKDIR /usr/app

# # Copy requirements first for better caching
# COPY requirements.txt ./

# # Install Python dependencies
# RUN pip3 install --upgrade pip setuptools wheel
# RUN pip3 install -r requirements.txt
# RUN pip3 install psycopg2-binary --no-binary psycopg2-binary

# # Copy application code
# COPY . ./

# # Create non-root user for security
# RUN useradd admin
# RUN chown -R admin:admin ./
# USER admin

# # Expose port 8000 for Django development server
# EXPOSE 8000

# # Default command (can be overridden in docker-compose)
# CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]


FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Use Gunicorn instead of runserver
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "maple_key_backend.wsgi:application"]