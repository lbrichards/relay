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

class InteractiveShell:
    """Manages an interactive shell session using PTY"""
    def __init__(self):
        self.master_fd = None
        self.shell_pid = None
        
    def start(self):
        """Start an interactive shell"""
        try:
            # Create a new PTY
            self.shell_pid, self.master_fd = pty.fork()
            
            if self.shell_pid == 0:  # Child process
                # Execute bash in the child
                os.execvp("bash", ["bash", "--login"])
            else:  # Parent process
                # Set the terminal size
                self._set_terminal_size(24, 80)
                print("DEBUG: Started interactive shell")
                return True
                
        except Exception as e:
            print(f"ERROR: Failed to start shell: {str(e)}")
            return False
            
    def _set_terminal_size(self, rows, cols):
        """Set the PTY window size"""
        try:
            term_size = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, term_size)
        except:
            pass
            
    def send_command(self, command):
        """Send a command to the shell"""
        try:
            # Add newline to execute the command
            full_command = command + "\n"
            os.write(self.master_fd, full_command.encode())
            time.sleep(0.1)  # Give shell time to process
            return True
        except Exception as e:
            print(f"ERROR: Failed to send command: {str(e)}")
            return False
            
    def stop(self):
        """Stop the shell"""
        try:
            if self.master_fd:
                os.close(self.master_fd)
            if self.shell_pid:
                os.kill(self.shell_pid, 9)
        except:
            pass

def create_tmate_session():
    """Create a new tmate session with interactive shell"""
    shell = InteractiveShell()
    if shell.start():
        return shell
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
