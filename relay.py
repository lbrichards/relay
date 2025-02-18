#!/usr/bin/env python3

import argparse
import redis
import sys
import time
import os
import subprocess
import glob
from datetime import datetime

def extract_tmate_urls(output):
    """Extract web and ssh URLs from tmate output"""
    web_ro = None
    ssh_ro = None
    
    for line in output.split('\n'):
        if 'web session read only:' in line:
            web_ro = line.split(': ', 1)[1].strip()
        elif 'ssh session read only:' in line:
            ssh_ro = line.split(': ', 1)[1].strip()
            
    return web_ro, ssh_ro

def get_tmate_socket():
    """Find the active tmate socket"""
    try:
        # Use glob to find tmate sockets
        sockets = glob.glob('/tmp/tmate-*')
        if sockets:
            # Get the most recently modified socket
            latest = max(sockets, key=os.path.getmtime)
            print(f"DEBUG: Found tmate socket: {latest}")
            return latest
        else:
            print("DEBUG: No tmate sockets found in /tmp")
    except Exception as e:
        print(f"DEBUG: Error finding tmate socket: {str(e)}")
    return None

def create_tmate_session():
    """Create a new tmate session with proper interactive shell"""
    try:
        # Start tmate with interactive shell
        subprocess.run(
            ["tmate", "new-session", "-d", "/bin/bash --login"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("DEBUG: Created tmate session with interactive shell")
        
        # Give the session a moment to initialize
        time.sleep(1)
        
        # Get the socket path
        socket_path = get_tmate_socket()
        if not socket_path:
            print("[ERROR] Could not find tmate socket after creating session")
            return None
            
        # Configure the session for proper terminal behavior
        subprocess.run(
            ["tmate", "-S", socket_path, "set", "-g", "status", "off"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        print("DEBUG: Configured tmate session")
        return socket_path
        
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to create tmate session: {str(e)}")
        return None

def get_tmate_urls(socket_path):
    """Get both web and ssh URLs from tmate session"""
    try:
        # First try to get URLs from socket
        result = subprocess.run(
            ['tmate', '-S', socket_path, 'show-messages'],
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            print("DEBUG: Got tmate messages output")
            return extract_tmate_urls(result.stdout)
        else:
            print("DEBUG: No output from tmate show-messages")
            
    except subprocess.CalledProcessError as e:
        print(f"DEBUG: Error getting tmate messages: {str(e)}")
    
    return None, None

def send_to_terminal(socket_path, command):
    """Send command to terminal, ready for execution"""
    if not socket_path:
        print("Error: No active tmate session found")
        return False
        
    try:
        # Send the command without executing it
        subprocess.run(
            ['tmate', '-S', socket_path, 'send-keys', command],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"DEBUG: Command staged in terminal: {command}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error sending command: {str(e)}")
        return False

def publish_urls_to_redis(r, web_url, ssh_url):
    """Publish tmate URLs to Redis for OpenHands to find"""
    try:
        urls = {
            'web': web_url,
            'ssh': ssh_url,
            'timestamp': datetime.now().isoformat()
        }
        r.set('tmate_urls', str(urls))
        return True
    except:
        return False

def start_relay(args):
    """Start a relay session with:
    1. Interactive tmate shell
    2. Redis connection for commands
    3. URL sharing
    """
    print("\nDEBUG: Starting relay with Redis host: localhost")
    
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
    except redis.ConnectionError:
        print("\n[ERROR] Cannot connect to Redis")
        print("Make sure Redis is running:")
        print("  Ubuntu/Debian: sudo service redis-server start")
        print("  macOS: brew services start redis")
        return
    except Exception as e:
        print(f"\n[ERROR] Redis error: {str(e)}")
        return

    # Create new tmate session
    socket_path = create_tmate_session()
    if not socket_path:
        print("[ERROR] Failed to create tmate session")
        return

    # Get URLs from tmate messages
    web_url, ssh_url = get_tmate_urls(socket_path)
    if web_url and ssh_url:
        print("\n✓ Found tmate URLs:")
        print(f"• Web (preferred): {web_url}")
        print(f"• SSH (alternate): {ssh_url}")
        
        # Publish URLs to Redis
        if publish_urls_to_redis(r, web_url, ssh_url):
            print("• URLs have been shared with OpenHands\n")
        else:
            print("• Failed to share URLs with OpenHands\n")
    else:
        print("[WARN] Could not get tmate URLs - will retry periodically")

    try:
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe('llm_suggestions')
        
        print("\n=== Relay Started ===")
        print("• Connected to Redis")
        print("• Subscribed to llm_suggestions channel")
        print("• Commands will appear here")
        print("• Press Ctrl-C to stop\n")
        
        for message in pubsub.listen():
            if message and message['type'] == 'message':
                command = message['data'].decode('utf-8')
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Command received:")
                print(f"➜ {command}")
                
                if send_to_terminal(socket_path, command):
                    print("✓ Command ready - press Enter to execute")
                else:
                    print("✗ Failed to send command to terminal")
                
    except KeyboardInterrupt:
        print("\n\n=== Relay stopped ===")
        sys.exit(0)

def stop_relay(args):
    """Stop the tmate session if running."""
    socket_path = get_tmate_socket()
    if socket_path:
        try:
            subprocess.run(
                ["tmate", "-S", socket_path, "kill-session"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("Relay session stopped.")
        except subprocess.CalledProcessError:
            print("Failed to stop relay session.")
    else:
        print("No active relay session found.")

def main():
    parser = argparse.ArgumentParser(
        description="Relay CLI: Display messages from LLM via Redis pub/sub"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Start command
    parser_start = subparsers.add_parser(
        "start",
        help="Start relay service"
    )
    parser_start.set_defaults(func=start_relay)

    # Stop command
    parser_stop = subparsers.add_parser(
        "stop",
        help="Stop relay service"
    )
    parser_stop.set_defaults(func=stop_relay)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)

if __name__ == "__main__":
    main()
