"""The `dink` command-line tool.

Each subcommand is built in its own ticket (docs/DESIGN.md section 14). Until then it prints
"not built yet" and exits with code 1, so scripts never mistake a placeholder for real work.
"""

from importlib.metadata import version as _pkg_version

import typer

app = typer.Typer(
    name="dink",
    help="DinkData: turn PickleCam recordings into per-player stats and highlight reels.",
    no_args_is_help=True,
)

PLACEHOLDERS = {
    "catalog": "Sync the list of PickleCam videos into the catalog.",
    "sample": "Pick the sample and gold games, holding out whole facilities.",
    "fetch": "Copy selected videos and their frame timestamps into storage.",
    "calibrate": "Calibrate a camera from clicked court points.",
    "run": "Run the pipeline on recordings.",
    "eval": "Score a pipeline run against the gold set.",
    "studio": "Open the labelling and review studio.",
    "report": "Build the one-page report for a game.",
    "highlights": "Build the highlight reels for a game.",
}


def _placeholder(name: str, summary: str) -> None:
    def command() -> None:
        typer.echo(f"`dink {name}` is not built yet. See docs/DESIGN.md section 14.", err=True)
        raise typer.Exit(code=1)

    command.__doc__ = summary
    app.command(name=name)(command)


for _name, _summary in PLACEHOLDERS.items():
    _placeholder(_name, _summary)


@app.callback()
def main() -> None:
    """DinkData: turn PickleCam recordings into per-player stats and highlight reels."""


@app.command()
def version() -> None:
    """Print the installed dinkdata version."""
    typer.echo(_pkg_version("dinkdata"))


if __name__ == "__main__":
    app()
