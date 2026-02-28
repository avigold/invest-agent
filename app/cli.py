"""CLI for Invest Agent."""
from __future__ import annotations

import subprocess
import sys

import typer

app_cli = typer.Typer(name="investagent", help="Invest Agent CLI")


@app_cli.command()
def run(task: str):
    """Run a named task. Currently supported: 'daily'."""
    if task == "daily":
        typer.echo("Daily scheduler: no tasks configured yet (M1 stub).")
    else:
        typer.echo(f"Unknown task: {task}")
        raise typer.Exit(1)


@app_cli.command()
def migrate():
    """Run Alembic migrations (upgrade head)."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )


@app_cli.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
):
    """Start the API server."""
    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
