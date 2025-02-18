#!/usr/bin/env python3

import argparse
import os
import subprocess
import threading
import time
import requests
from bs4 import BeautifulSoup

SOCKET_PATH = "/tmp/tmate.sock"
WATCH_URL = "http://192.168.3.52:51753/command"  # AI Bridge endpoint that returns <div id="command">TEXT</div>

def watch_webpage(interval_sec=1):
    """
    Watch the AI Bridge webpage for command changes.
    When a change is detected, display it in the terminal.
    """
    last_text = None
    connection_error_shown = False
    
    print(f"\n[relay] Watching {WATCH_URL} for commands")
    print("[relay] Commands received will appear here\n")
    
    while True:
        if not is_tmate_session_alive():
            print("\n[ERROR] Tmate session lost! Please restart relay.")
            break

        try:
            resp = requests.get(WATCH_URL, timeout=5)
            resp.raise_for_status()
            
            if connection_error_shown:
                print("\n[relay] ✓ Connection to AI Bridge restored")
                connection_error_shown = False
                
            soup = BeautifulSoup(resp.text, "html.parser")
            div_cmd = soup.find(id="command")
            if div_cmd:
                current_text = div_cmd.get_text(strip=True)
                if current_text and current_text != last_text:
                    # Clear line and move cursor to start
                    print("\r\033[K", end="")
                    
                    # Print received command
                    print("\n\033[1m=== Command Received ===\033[0m")
                    print(f"{current_text}")
                    print("\033[1m" + "="*24 + "\033[0m\n")
                    
                    # Echo command to tmate session
                    if send_keys_to_tmate(current_text):
                        last_text = current_text
            
        except requests.RequestException as e:
            if not connection_error_shown:
                print("\n[relay] ✗ Cannot connect to AI Bridge")
                print(f"[relay] Make sure AI Bridge is running on port 51753")
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
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "send-keys", "C-u"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        # Break long text into chunks
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        
        for chunk in chunks:
            subprocess.run(
                ["tmate", "-S", SOCKET_PATH, "send-keys", chunk],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            time.sleep(0.1)  # Small delay between chunks
        
        # Add final newline
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "send-keys", "Enter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to send command to tmate: {str(e)}")
        return False

def wait_for_tmate_ready(timeout=30):
    """Wait for tmate to be ready and return session links."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Try to get session links
            ssh_ro = subprocess.check_output(
                ["tmate", "-S", SOCKET_PATH, "display", "-p", "#{tmate_ssh_ro}"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            if ssh_ro and "ssh" in ssh_ro:
                return ssh_ro
        except:
            pass
        time.sleep(1)
    return None

def start_relay(args):
    """Start a relay session that:
    1. Creates a tmate session for sharing terminal
    2. Provides read-only access link
    3. Watches AI Bridge for commands
    4. Echoes commands to the terminal
    """
    print("\n=== Starting Relay Session ===")
    
    # Check if tmate is installed
    try:
        subprocess.run(["tmate", "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[ERROR] tmate is not installed")
        print("Please install tmate first:")
        print("  Ubuntu/Debian: sudo apt-get install tmate")
        print("  macOS: brew install tmate")
        return
    
    # Kill any existing session quietly
    if is_tmate_session_alive():
        print("• Cleaning up existing tmate session...")
        try:
            subprocess.run(
                ["tmate", "-S", SOCKET_PATH, "kill-session"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            time.sleep(1)  # Give time for cleanup
        except subprocess.CalledProcessError:
            print("[WARN] Could not clean up old session, but continuing...")

    # Create a new session
    print("• Creating tmate session...")
    
    # Clean environment
    if "TMUX" in os.environ:
        del os.environ["TMUX"]
    os.environ["TMATE_NOPROMPT"] = "1"
    
    # Start tmate in a clean way
    try:
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "new-session", "-d", "bash"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
    except subprocess.CalledProcessError:
        print("[ERROR] Failed to create tmate session")
        return
        
    # Wait for session to be ready and get link
    print("• Waiting for session to be ready...")
    ssh_ro_link = wait_for_tmate_ready()
    if not ssh_ro_link:
        print("[ERROR] Tmate session failed to initialize")
        return
        
    print(f"\n✓ Share this link with the LLM:")
    print(f"  {ssh_ro_link}")

    # Start background thread to watch the webpage
    print("\n• Starting command relay...")
    watcher_thread = threading.Thread(target=watch_webpage, daemon=True)
    watcher_thread.start()

    # Show instructions and attach
    print("\n• Commands will appear here when received")
    print("• Press Ctrl-B D to detach (session stays active)")
    print("• Use 'relay stop' to end completely\n")
    
    try:
        # Clear screen and attach
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "send-keys", "clear", "Enter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "attach"],
            check=True
        )
        
        print("\n=== Detached from relay session ===")
        if is_tmate_session_alive():
            print("• Session is still running and receiving commands")
            print("• Use 'relay stop' to end it completely\n")
    except subprocess.CalledProcessError:
        print("\n=== Relay session ended ===\n")

def stop_relay(args):
    """Stop the tmate session if running."""
    try:
        subprocess.run(
            ["tmate", "-S", SOCKET_PATH, "kill-session"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        print("Relay session stopped.")
    except subprocess.CalledProcessError:
        print("No active relay session found.")

def main():
    parser = argparse.ArgumentParser(description="Relay CLI: Watch AI Bridge and relay commands to terminal.")
    subparsers = parser.add_subparsers(dest="command")

    parser_start = subparsers.add_parser("start", help="Start relay session.")
    parser_start.set_defaults(func=start_relay)

    parser_stop = subparsers.add_parser("stop", help="Stop relay session.")
    parser_stop.set_defaults(func=stop_relay)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)

if __name__ == "__main__":
    main()