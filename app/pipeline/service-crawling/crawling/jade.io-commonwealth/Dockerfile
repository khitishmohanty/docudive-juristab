# Use a standard, slim Python base image
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies
# - curl, unzip: to get the browser and driver
# - libnss3, libgconf-2-4, etc: required by headless Chrome
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    libnss3 \
    libgconf-2-4 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libxss1 \
    libasound2 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Install Chrome and ChromeDriver (same logic as before, just using apt-get)
RUN curl -Lo "/tmp/chromedriver.zip" "https://storage.googleapis.com/chrome-for-testing-public/125.0.6422.78/linux64/chromedriver-linux64.zip" && \
    unzip /tmp/chromedriver.zip -d /usr/local/bin/ && \
    rm /tmp/chromedriver.zip

RUN curl -Lo "/tmp/chrome.zip" "https://storage.googleapis.com/chrome-for-testing-public/125.0.6422.78/linux64/chrome-linux64.zip" && \
    unzip /tmp/chrome.zip -d /opt/ && \
    rm /tmp/chrome.zip

# Set environment variables for Selenium
ENV PATH="/usr/local/bin/chromedriver-linux64:${PATH}"
# Point to the new chrome binary location
ENV CHROME_BIN=/opt/chrome-linux64/chrome

# Add a non-root user for security best practice
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Application User" appuser

# Copy application files and set ownership
COPY --chown=appuser:appuser . .

# Install Python packages
RUN python -m pip install --no-cache-dir -r requirements.txt

# Switch to the non-root user
USER appuser

# Set the command to run when the container starts
# This directly executes your script
CMD [ "python", "crawler.py" ]