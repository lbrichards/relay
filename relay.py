#!/usr/bin/env python3

import typer
import redis
from datetime import datetime
from typing import Optional

app = typer.Typer()

@app.command()
def start():
    """Start the relay service"""
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    
    try:
        redis_client.ping()
        typer.echo("Connected to Redis")
    except redis.ConnectionError:
        typer.echo("Error: Could not connect to Redis")
        raise typer.Exit(1)
    
    # Subscribe to Redis channel
    pubsub = redis_client.pubsub()
    pubsub.subscribe('llm_suggestions')
    typer.echo("Subscribed to llm_suggestions channel")
    
    # Listen for messages
    try:
        for message in pubsub.listen():
            if message['type'] == 'message':
                command = message['data'].decode('utf-8')
                typer.echo(f"\nReceived command: {command}")
                # Execute command
                typer.launch(command)
    except KeyboardInterrupt:
        typer.echo("\nRelay stopped")

def main():
    app()

if __name__ == "__main__":
    main()

def create_shell():
    """Create a new interactive shell"""
    shell = CommandShell()
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
    if not shell or not isinstance(shell, CommandShell):
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

    # Create interactive shell
    shell = create_shell()
    if not shell:
        print("[ERROR] Failed to create interactive shell")
        return

    print("\n✓ Interactive shell ready")
    print("• Commands will be executed in this terminal")
    print("• Press Ctrl-C to stop\n")

    shell = None
    try:
        # Start interactive shell
        shell = create_shell()
        if not shell:
            print("[ERROR] Failed to create interactive shell")
            return

        print("\n✓ Interactive shell ready")
        print("• Commands will be executed in this terminal")
        print("• Press Ctrl-C to stop\n")

        # Connect to Redis
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe('llm_suggestions')
        
        print("=== Relay Started ===")
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
