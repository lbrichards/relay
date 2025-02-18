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

@app.command()
def stop():
    """Stop the relay service"""
    typer.echo("Stopping relay...")
    raise typer.Exit()

def main():
    app()

if __name__ == "__main__":
    main()
