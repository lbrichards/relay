#!/usr/bin/env python3

import argparse
import subprocess
import sys
import time
import os

# For optional web-watching:
import requests
from bs4 import BeautifulSoup

# Default path where we store the tmate socket
SOCKET_PATH = "/tmp/relay_tmate.sock"

def start_relay(args):
    """
    Start a new tmate session in detached mode, wait until it's ready,
    then print the read-only link to stdout.
    """
    # 1) Create a new session in detached mode
    subprocess.run(["tmate", "-S", SOCKET_PATH, "new-session", "-d"], check=True)
    # 2) Wait for tmate to be ready
    subprocess.run(["tmate", "-S", SOCKET_PATH, "wait", "tmate-ready"], check=True)

    # 3) Retrieve read-only link
    ssh_ro_link = subprocess.check_output(
        ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_ssh_ro}"]
    ).decode("utf-8").strip()

    # Show the user
    print(f"Read-Only Link: {ssh_ro_link}")

def stop_relay(args):
    """
    Kill the tmate session (if it exists).
    """
    try:
        subprocess.run(["tmate", "-S", SOCKET_PATH, "kill-session"], check=True)
        print("Tmate session stopped.")
    except subprocess.CalledProcessError:
        print("No active tmate session found (or already stopped).")

def status_relay(args):
    """
    Check if the tmate session is running, and if so, show the read-only link.
    """
    # We'll attempt to get the read-only link. If it fails, presumably tmate isn't running.
    try:
        ro_link = subprocess.check_output(
            ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_ssh_ro}"]
        ).decode().strip()
        print(f"Tmate session is running.\nRead-Only Link: {ro_link}")
    except subprocess.CalledProcessError:
        print("No active tmate session is running at the specified socket.")

def watch_web(args):
    """
    Periodically fetch the given URL, look for <div id="command">,
    and if the text changes, 'send-keys' into the tmate session.
    """
    url = args.url
    interval = args.interval

    last_seen_text = None
    print(f"Starting to watch {url} every {interval} seconds...")

    while True:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            time.sleep(interval)
            continue

        # Parse HTML to find the <div id="command">
        soup = BeautifulSoup(response.text, "html.parser")
        div_cmd = soup.find(id="command")
        if div_cmd:
            current_text = div_cmd.get_text(strip=True)
            if current_text and current_text != last_seen_text:
                print(f"New command detected: {current_text}")
                send_to_tmate(current_text)
                last_seen_text = current_text

        time.sleep(interval)

def send_to_tmate(text):
    """
    Use 'tmate -S ... send-keys' to inject `text` into the first window/pane,
    then press Enter.
    """
    cmd = [
        "tmate",
        "-S", SOCKET_PATH,
        "send-keys",
        "-t", "0",
        text,
        "Enter"
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to send keys to tmate session. Is it running?\n{e}")

def main():
    parser = argparse.ArgumentParser(
        description="Relay CLI: Manage a tmate session and optionally watch a webpage."
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # relay start
    parser_start = subparsers.add_parser("start", help="Start tmate session")
    parser_start.set_defaults(func=start_relay)

    # relay stop
    parser_stop = subparsers.add_parser("stop", help="Stop tmate session")
    parser_stop.set_defaults(func=stop_relay)

    # relay status
    parser_status = subparsers.add_parser("status", help="Check tmate session status")
    parser_status.set_defaults(func=status_relay)

    # relay watch-web
    parser_watch = subparsers.add_parser("watch-web", help="Watch a webpage <div id='command'> and inject it into tmate.")
    parser_watch.add_argument("--url", required=True, help="URL of the page to watch for commands")
    parser_watch.add_argument("--interval", type=int, default=5, help="Interval in seconds between checks")
    parser_watch.set_defaults(func=watch_web)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to the correct function
    args.func(args)

if __name__ == "__main__":
    main()