#!/usr/bin/env python3

import argparse
import redis
import sys
import time
import subprocess
from datetime import datetime

SOCKET_PATH = "/tmp/tmate.sock"

def send_to_terminal(command):
    """Send command to terminal, ready for execution"""
    try:
        # Clear any existing input
        subprocess.run(['tmate', '-S', SOCKET_PATH, 'send-keys', 'C-u'], check=True)
        # Send the command
        subprocess.run(['tmate', '-S', SOCKET_PATH, 'send-keys', command], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {str(e)}")
        return False

def start_relay(args):
    """
    Start the relay service that:
    1. Connects to Redis
    2. Subscribes to llm_suggestions channel
    3. Displays formatted messages as they arrive
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