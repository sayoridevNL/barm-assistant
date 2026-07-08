FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg git fonts-liberation fonts-noto-color-emoji && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces require running as a non-root user
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy the project files
COPY --chown=user . $HOME/app

# Install Python requirements
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Hugging Face Spaces routes traffic to port 7860 by default
ENV PORT=7860
EXPOSE 7860

# Start the web dashboard using gunicorn
CMD ["python", "-u", "server.py"]
