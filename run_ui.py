#!/usr/bin/env python3
"""
Launcher for Wallpics Ultra-HD Scraper UI.
Starts the local Flask web server and automatically opens your default browser.
"""

import os
import sys
import threading
import time
import webbrowser
from app import app

PORT = 5000

def open_browser():
    time.sleep(1.2)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Opening browser at: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    print("=" * 60)
    print(" Wallpics PRO MAX - Ultra-HD Image Scraper UI")
    print(f" Running at: http://127.0.0.1:{PORT}")
    print(" Press Ctrl+C in this terminal to stop the server.")
    print("=" * 60)
    app.run(host="127.0.0.1", port=PORT, debug=False)
