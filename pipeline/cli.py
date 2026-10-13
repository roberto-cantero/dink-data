"""`dink-cv` command-line entry point.

Subcommands (run, ball, eval, render) are added as each stage is ported.
"""

from importlib.metadata import version as _pkg_version

import typer

app = typer.Typer(
    name="dink-cv",
    help="DinkData CV pipeline: turn a PickleCam video into court, ball, players and events.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """DinkData CV pipeline."""


@app.command()
def version() -> None:
    """Print the installed dinkdata version."""
    typer.echo(_pkg_version("dinkdata"))


if __name__ == "__main__":
    app()
