FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg git fonts-liberation fonts-noto-color-emoji build-essential libffi-dev libsodium-dev python3-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the project files
COPY . /app

# Install Python requirements
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --retries 5 --timeout 100 -r requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 100 -U --pre yt-dlp

# Render automatically injects the PORT environment variable
# Expose the default Render port just in case
EXPOSE 10000

# Start the web dashboard using gunicorn
CMD gunicorn --bind 0.0.0.0:$PORT server:app