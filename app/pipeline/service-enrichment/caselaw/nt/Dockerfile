# Dockerfile

# --- Stage 1: Build stage ---
# Use an official Python runtime as a parent image
FROM python:3.11-slim as builder

# Set the working directory in the container
WORKDIR /app

# Install build dependencies
RUN pip install --upgrade pip

# Copy the requirements file and install dependencies
# This is done in a separate step to leverage Docker's layer caching
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# --- Stage 2: Final stage ---
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the pre-built wheels from the builder stage
COPY --from=builder /app/wheels /wheels

# Install the dependencies from the wheels
RUN pip install --no-cache /wheels/*

# Copy your application's source code and configuration into the container
COPY src/ ./src
COPY config/ ./config
COPY main.py .

# Define the command to run your application
# This tells Fargate how to start your program
CMD ["python", "main.py"]