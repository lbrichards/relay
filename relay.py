#!/usr/bin/env python3

import argparse
import os
import subprocess
import threading
import time
import requests
from bs4 import BeautifulSoup

SOCKET_PATH = "/tmp/relay_tmate.sock"
WATCH_URL = "http://127.0.0.1:51753/command"  # Our GET endpoint that returns <div id="command">TEXT</div>

def watch_webpage(interval_sec=5):
    """
    Periodically fetch WATCH_URL, look for <div id="command">,
    and if changed, send keys to tmate session.
    We only print a line when new text is actually detected (not every fetch).
    """
    last_text = None
    while True:
        try:
            resp = requests.get(WATCH_URL, timeout=10)
            resp.raise_for_status()
        except Exception:
            # Suppress fetch/HTTP errors, so no repeated logs every interval.
            time.sleep(interval_sec)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        div_cmd = soup.find(id="command")
        if div_cmd:
            current_text = div_cmd.get_text(strip=True)
            if current_text and current_text != last_text:
                print(f"[watch-web] New text detected: {current_text}")
                send_keys_to_tmate(current_text)
                last_text = current_text

        time.sleep(interval_sec)


def send_keys_to_tmate(text):
    print(f"[watch-web] Injecting line to tmate (0.0): {text}")
    try:
        # Force a fresh line
        subprocess.run([
            "tmate", "-S", SOCKET_PATH,
            "send-keys",
            "-t", "0.0",
            "Enter"
        ], check=True)

        # Insert the text, no Enter
        subprocess.run([
            "tmate", "-S", SOCKET_PATH,
            "send-keys",
            "-t", "0.0",
            text
        ], check=True)

        print("[watch-web] Injection complete.")
    except subprocess.CalledProcessError as e:
        print(f"[watch-web] ERROR: {e}")
def start_relay(args):
    """
    1) Kills any existing tmate session on SOCKET_PATH
    2) Creates a new session
    3) Prints read-only link
    4) Starts web watcher thread
    5) Attaches locally
    """
    # Kill any existing session quietly
    subprocess.run(
        ["tmate", "-S", SOCKET_PATH, "kill-session"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Create a new session in detached mode (minimal shell)
    # Suppress tmate welcome prompt
    os.environ["TMATE_NOPROMPT"] = "1"
    subprocess.run(
        ["tmate", "-S", SOCKET_PATH, "new-session", "-d", "bash", "--noprofile", "--norc"],
        check=True
    )

    # Wait for tmate-ready
    subprocess.run(["tmate", "-S", SOCKET_PATH, "wait", "tmate-ready"], check=True)

    # Retrieve read-only link
    ssh_ro_link = subprocess.check_output(
        ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_ssh_ro}"]
    ).decode("utf-8").strip()

    print(f"Read-Only Link: {ssh_ro_link}")

    # Start background thread to watch the webpage
    watcher_thread = threading.Thread(target=watch_webpage, daemon=True)
    watcher_thread.start()

    # Attach locally
    print("Attaching locally to tmate session. (Detach: Ctrl-B D, or 'exit')")
    subprocess.run(["tmate", "-S", SOCKET_PATH, "attach"])
    print("Detached or session ended.")

def stop_relay(args):
    """Stop the tmate session if running."""
    try:
        subprocess.run(["tmate", "-S", SOCKET_PATH, "kill-session"], check=True)
        print("Tmate session stopped.")
    except subprocess.CalledProcessError:
        print("No active tmate session found (or already stopped).")

def main():
    parser = argparse.ArgumentParser(description="Relay CLI: Single command to run tmate + watch a web page.")
    subparsers = parser.add_subparsers(dest="command")

    parser_start = subparsers.add_parser("start", help="Start tmate session + webpage watcher.")
    parser_start.set_defaults(func=start_relay)

    parser_stop = subparsers.add_parser("stop", help="Stop tmate session.")
    parser_stop.set_defaults(func=stop_relay)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)

if __name__ == "__main__":
    main()