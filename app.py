import os
import sys

if __name__ == "__main__":
    print("Starting Flask server under Gradio Space wrapper...")
    os.system("gunicorn --bind 0.0.0.0:7860 server:app")
