#!/usr/bin/env python3
"""
GhostScrapy App Launcher
Starts the Flask server and optionally creates an ngrok public tunnel.

Usage:
    python3 run.py            # Local mode: http://localhost:5050
    python3 run.py --ngrok    # Public mode: generates public https://...ngrok-free.app URL
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import json
import webbrowser

PORT = 5050


def find_ngrok():
    """Find path to ngrok binary."""
    path = shutil.which("ngrok")
    if path:
        return path
    standard_paths = [
        "/opt/homebrew/bin/ngrok",
        "/usr/local/bin/ngrok",
        os.path.expanduser("~/bin/ngrok"),
    ]
    for p in standard_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def get_ngrok_url(timeout=10):
    """Query ngrok client API to retrieve the assigned public URL."""
    api_url = "http://127.0.0.1:4040/api/tunnels"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                tunnels = data.get("tunnels", [])
                for t in tunnels:
                    if t.get("proto") == "https":
                        return t.get("public_url")
                    if t.get("public_url", "").startswith("https"):
                        return t.get("public_url")
                if tunnels:
                    return tunnels[0].get("public_url")
        except Exception:
            time.sleep(0.5)
    return None


def main():
    use_ngrok = "--ngrok" in sys.argv
    ngrok_process = None
    public_url = None

    print(f"Starting GhostScrapy on port {PORT}...")

    if use_ngrok:
        ngrok_bin = find_ngrok()
        if not ngrok_bin:
            print("[warning] ngrok binary not found in PATH. Falling back to local mode.")
        else:
            print(f"[ngrok] Launching tunnel via {ngrok_bin}...")
            try:
                ngrok_process = subprocess.Popen(
                    [ngrok_bin, "http", str(PORT)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                public_url = get_ngrok_url()
                if public_url:
                    print(f"[ngrok] Public URL: {public_url}")
                else:
                    print("[ngrok] Tunnel started. If prompt requires an auth token, run: ngrok config add-authtoken <TOKEN>")
            except Exception as e:
                print(f"[warning] Failed to start ngrok: {e}")

    local_url = f"http://localhost:{PORT}"
    print(f"Local URL:  {local_url}")
    print("Press Ctrl+C to stop the server.\n")

    # Auto-open browser
    target_browser_url = public_url if public_url else local_url
    try:
        webbrowser.open(target_browser_url)
    except Exception:
        pass

    # Import and run Flask app
    from app import app
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[GhostScrapy] Shutting down...")
    finally:
        if ngrok_process:
            ngrok_process.terminate()
            ngrok_process.wait()
            print("[ngrok] Tunnel closed.")


if __name__ == "__main__":
    main()

