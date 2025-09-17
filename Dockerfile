# Django Backend Dockerfile for Maple Key Music Academy
# Optimized for development with PostgreSQL support

FROM python:3.11-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get -y update && apt-get -y upgrade
RUN apt-get -y install \
    postgresql \
    postgresql-contrib \
    build-essential \
    libpq-dev

# Set working directory
WORKDIR /usr/app

# Copy requirements first for better caching
COPY requirements.txt ./

# Install Python dependencies
RUN pip3 install --upgrade pip setuptools wheel
RUN pip3 install -r requirements.txt
RUN pip3 install psycopg2-binary --no-binary psycopg2-binary

# Copy application code
COPY . ./

# Create non-root user for security
RUN useradd admin
RUN chown -R admin:admin ./
USER admin

# Expose port 8000 for Django development server
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]
