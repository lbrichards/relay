#!/usr/bin/env python3

import argparse
import redis
import sys
import time
import os
import subprocess
import glob
from datetime import datetime

def get_tmate_urls(socket_path):
    """Get both web and ssh URLs for the tmate session"""
    try:
        web_ro = subprocess.check_output(
            ['tmate', '-S', socket_path, 'display', '-p', '#{tmate_web_ro}'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        ssh_ro = subprocess.check_output(
            ['tmate', '-S', socket_path, 'display', '-p', '#{tmate_ssh_ro}'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        return web_ro, ssh_ro
    except subprocess.CalledProcessError:
        return None, None

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

def send_to_terminal(command):
    """Send command to terminal, ready for execution"""
    socket_path = get_tmate_socket()
    if not socket_path:
        print("Error: No active tmate session found")
        return False
        
    try:
        # Clear any existing input
        subprocess.run(['tmate', '-S', socket_path, 'send-keys', '-l', command], 
                      check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Send Enter key
        subprocess.run(['tmate', '-S', socket_path, 'send-keys', 'Enter'],
                      check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"DEBUG: Command sent via {socket_path}")
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
    """
    Start the relay service that:
    1. Connects to Redis
    2. Subscribes to llm_suggestions channel
    3. Publishes tmate URLs to Redis
    4. Displays formatted messages as they arrive
    """
    print("\nDEBUG: Starting relay with Redis host: localhost")
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        # Test connection
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

    # Get tmate socket and URLs
    socket_path = get_tmate_socket()
    if not socket_path:
        print("[ERROR] No active tmate session found")
        return

    web_url, ssh_url = get_tmate_urls(socket_path)
    if not web_url or not ssh_url:
        print("[ERROR] Could not get tmate URLs")
        return

    # Publish URLs to Redis
    if publish_urls_to_redis(r, web_url, ssh_url):
        print("\n✓ Session URLs:")
        print(f"• Web (preferred): {web_url}")
        print(f"• SSH (alternate): {ssh_url}")
        print("URLs have been shared with OpenHands\n")

    try:
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe('llm_suggestions')
        print("DEBUG: Subscribed to Redis channel 'llm_suggestions'")
        
        print("\n=== Relay Started ===")
        print("• Connected to Redis")
        print("• Subscribed to llm_suggestions channel")
        print("• Messages from LLM will appear here")
        print("• Press Ctrl-C to stop\n")
        
        for message in pubsub.listen():
            print(f"DEBUG: Received message: {message}")
            if message and message['type'] == 'message':
                # Clear line and print with timestamp
                print("\r\033[K", end="")
                timestamp = datetime.now().strftime("%H:%M:%S")
                command = message['data'].decode('utf-8')
                print(f"\n[{timestamp}] Sending command to terminal...")
                
                if send_to_terminal(command):
                    print("\n✓ Command ready")
                    print("• Press Enter to execute\n")
                else:
                    print("\n✗ Could not send command to terminal")
                    print("• Please type the command manually\n")
                
    except KeyboardInterrupt:
        print("\n\n=== Relay stopped ===")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
        sys.exit(1)

def stop_relay(args):
    """
    Stop the relay service by unsubscribing from Redis.
    """
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        # Publish a special message to indicate stopping
        r.publish('llm_suggestions', '=== Relay stopping ===')
        print("Relay stopped.")
    except:
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