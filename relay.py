#!/usr/bin/env python3

import argparse
import redis
import sys
import time
import os
import pty
import subprocess
import glob
import fcntl
import termios
import struct
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

class CommandPipe:
    """Manages command input through a named pipe"""
    def __init__(self):
        self.pipe_path = "/tmp/relay_commands"
        self.pipe_fd = None
        
    def start(self):
        """Create the named pipe"""
        try:
            # Remove existing pipe if any
            if os.path.exists(self.pipe_path):
                os.unlink(self.pipe_path)
                
            # Create new pipe
            os.mkfifo(self.pipe_path)
            
            # Open pipe for writing (non-blocking)
            self.pipe_fd = os.open(self.pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            
            print("DEBUG: Created command pipe")
            
            # Start a shell that reads from the pipe
            subprocess.Popen(
                f"cat {self.pipe_path} | bash",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            return True
                
        except Exception as e:
            print(f"ERROR: Failed to create pipe: {str(e)}")
            return False
            
    def send_command(self, command):
        """Send a command through the pipe"""
        try:
            # Add newline to execute the command
            full_command = command + "\n"
            os.write(self.pipe_fd, full_command.encode())
            return True
        except Exception as e:
            print(f"ERROR: Failed to send command: {str(e)}")
            return False
            
    def stop(self):
        """Clean up the pipe"""
        try:
            if self.pipe_fd:
                os.close(self.pipe_fd)
            if os.path.exists(self.pipe_path):
                os.unlink(self.pipe_path)
        except:
            pass

def create_command_pipe():
    """Create a new command pipe for shell interaction"""
    pipe = CommandPipe()
    if pipe.start():
        return pipe
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

def send_to_terminal(shell, command):
    """Send command to terminal, ready for execution"""
    if not shell:
        print("Error: No active shell session")
        return False
        
    return shell.send_command(command)

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

    # Create command pipe
    pipe = create_command_pipe()
    if not pipe:
        print("[ERROR] Failed to create command pipe")
        return

    print("\n✓ Command pipe ready")
    print("• Commands will be executed in this terminal")
    print("• Press Ctrl-C to stop\n")

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
                
                if send_to_terminal(shell, command):
                    print("✓ Command sent to shell")
                else:
                    print("✗ Failed to send command to shell")
                
    except KeyboardInterrupt:
        print("\n\n=== Relay stopped ===")
        sys.exit(0)

def stop_relay(args):
    """Stop any running shell processes."""
    try:
        # Find and kill any relay processes
        subprocess.run(
            ["pkill", "-f", "relay"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("Relay session stopped.")
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
