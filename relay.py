#!/usr/bin/env python3

import typer
import redis
import subprocess
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
                try:
                    # Start an interactive shell process
                    process = subprocess.Popen(
                        ['/bin/bash', '-c', command],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,  # Line buffered
                        universal_newlines=True
                    )
                    
                    # Read output and error streams line by line
                    while True:
                        output = process.stdout.readline()
                        error = process.stderr.readline()
                        
                        if output:
                            typer.echo(output.rstrip())
                        if error:
                            typer.echo(error.rstrip(), err=True)
                            
                        # Break if process is done and no more output
                        if process.poll() is not None and not output and not error:
                            break
                            
                    # Get final return code
                    return_code = process.wait()
                    if return_code != 0:
                        typer.echo(f"Command exited with code {return_code}", err=True)
                        
                except Exception as e:
                    typer.echo(f"Error executing command: {str(e)}", err=True)
    except KeyboardInterrupt:
        typer.echo("\nRelay stopped")

@app.command()
def stop():
    """Stop the relay service"""
    typer.echo("Stopping relay...")
    raise typer.Exit()

def main():
    app()

if __name__ == "__main__":
    main()
