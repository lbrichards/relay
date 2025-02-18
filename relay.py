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
    Provides continuous status updates about connection and content.
    """
    last_text = None
    connection_error_shown = False
    print(f"\n[watch-web] Starting to watch {WATCH_URL}")
    print("[watch-web] Waiting for commands...\n")
    
    while True:
        # Check tmate session status
        if not is_tmate_session_alive():
            print("[ERROR] Tmate session is not running! Please restart relay.")
            break

        try:
            resp = requests.get(WATCH_URL, timeout=10)
            resp.raise_for_status()
            
            if connection_error_shown:
                print("[watch-web] ✓ Connection restored")
                connection_error_shown = False
                
            soup = BeautifulSoup(resp.text, "html.parser")
            div_cmd = soup.find(id="command")
            if div_cmd:
                current_text = div_cmd.get_text(strip=True)
                if current_text and current_text != last_text:
                    print("\n" + "="*50)
                    print(f"[watch-web] New command received:")
                    print(f"➜ {current_text}")
                    print("="*50 + "\n")
                    send_keys_to_tmate(current_text)
                    last_text = current_text
            
        except requests.RequestException as e:
            if not connection_error_shown:
                print(f"\n[watch-web] ✗ Cannot connect to {WATCH_URL}")
                print(f"[watch-web] Make sure the web server is running on port 51753")
                connection_error_shown = True

        time.sleep(interval_sec)


def is_tmate_session_alive():
    """Check if the tmate session is running."""
    try:
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "has-session"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def send_keys_to_tmate(text, chunk_size=100):
    """Send text to tmate session, breaking long text into chunks."""
    if not is_tmate_session_alive():
        print("[ERROR] Tmate session is not alive. Cannot send keys.")
        return False

    try:
        # Force a fresh line
        subprocess.run([
            "tmate", "-S", SOCKET_PATH,
            "send-keys",
            "-t", "0.0",
            "C-u"  # Clear line
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Break long text into chunks
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        
        for chunk in chunks:
            subprocess.run([
                "tmate", "-S", SOCKET_PATH,
                "send-keys",
                "-t", "0.0",
                chunk
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.1)  # Small delay between chunks
        
        # Add final newline
        subprocess.run([
            "tmate", "-S", SOCKET_PATH,
            "send-keys",
            "-t", "0.0",
            "Enter"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("[watch-web] ✓ Command sent successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to send command to tmate: {str(e)}")
        return False
def start_relay(args):
    """
    1) Kills any existing tmate session on SOCKET_PATH
    2) Creates a new session
    3) Prints read-only link
    4) Starts web watcher thread
    5) Attaches locally
    """
    print("\n=== Starting Relay ===")
    
    # Check if tmate is installed
    try:
        subprocess.run(["tmate", "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[ERROR] tmate is not installed. Please install it first.")
        return
    
    # Kill any existing session quietly
    if is_tmate_session_alive():
        print("• Cleaning up existing tmate session...")
        try:
            subprocess.run(
                ["tmate", "-S", SOCKET_PATH, "kill-session"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True
            )
            time.sleep(1)  # Give time for cleanup
        except subprocess.CalledProcessError:
            print("[WARN] Could not clean up old session, but continuing...")

    # Create a new session in detached mode (minimal shell)
    print("• Creating new tmate session...")
    os.environ["TMATE_NOPROMPT"] = "1"
    
    # Retry session creation a few times
    max_retries = 3
    for attempt in range(max_retries):
        try:
            subprocess.run(
                ["tmate", "-S", SOCKET_PATH, "new-session", "-d", "bash", "--noprofile", "--norc"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            break
        except subprocess.CalledProcessError:
            if attempt == max_retries - 1:
                print("[ERROR] Failed to create tmate session after multiple attempts")
                return
            print(f"• Retrying session creation (attempt {attempt + 2}/{max_retries})...")
            time.sleep(2)

    # Wait for tmate-ready with timeout
    print("• Waiting for tmate session to be ready...")
    timeout = time.time() + 30  # 30 second timeout
    while time.time() < timeout:
        try:
            subprocess.run(
                ["tmate", "-S", SOCKET_PATH, "wait", "tmate-ready"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if time.time() >= timeout:
                print("[ERROR] Tmate session failed to initialize (timeout)")
                return
            time.sleep(1)
            continue

    # Retrieve read-only link with retries
    print("• Getting session links...")
    for attempt in range(3):
        try:
            ssh_ro_link = subprocess.check_output(
                ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_ssh_ro}"],
                timeout=5
            ).decode("utf-8").strip()
            
            web_ro_link = subprocess.check_output(
                ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_web_ro}"],
                timeout=5
            ).decode("utf-8").strip()
            
            print(f"\n✓ SSH Read-Only:  {ssh_ro_link}")
            print(f"✓ Web Read-Only:  {web_ro_link}")
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                print("[ERROR] Failed to get session links")
                return
            time.sleep(2)
            continue

    # Start background thread to watch the webpage
    print("\n• Starting web watcher...")
    watcher_thread = threading.Thread(target=watch_webpage, daemon=True)
    watcher_thread.start()

    # Attach locally
    print("\n✓ Relay is ready!")
    print("• Commands from the web will appear here and be sent to the tmate session")
    print("• To detach: Ctrl-B D, or type 'exit'")
    print("• Session will remain active after detaching\n")
    
    try:
        subprocess.run(["tmate", "-S", SOCKET_PATH, "attach"], check=True)
        print("\n=== Detached from relay session ===")
    except subprocess.CalledProcessError:
        print("\n=== Relay session ended unexpectedly ===")
    
    if is_tmate_session_alive():
        print("• Session is still running. Use 'relay stop' to end it completely.\n")
    else:
        print("• Session has ended.\n")

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