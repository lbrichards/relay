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

    # Get tmate socket
    socket_path = get_tmate_socket()
    if not socket_path:
        print("[ERROR] No active tmate session found")
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