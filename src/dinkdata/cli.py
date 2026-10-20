"""The `dink` command-line tool.

Each subcommand is built in its own ticket (docs/DESIGN.md section 14). Until then it prints
"not built yet" and exits with code 1, so scripts never mistake a placeholder for real work.
"""

import os
from enum import StrEnum
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

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


contracts_app = typer.Typer(help="File formats: JSON Schemas generated from the pydantic models.")
app.add_typer(contracts_app, name="contracts")


@contracts_app.command("export")
def contracts_export(
    out: Annotated[Path, typer.Option(help="Folder for the *.schema.json files.")] = Path(
        "contracts"
    ),
    check: Annotated[bool, typer.Option(help="Only check that the schemas are current.")] = False,
) -> None:
    """Write contracts/*.schema.json from the models, or check that they are current."""
    from dinkdata.contracts.export import stale_schemas, write_schemas

    if check:
        stale = stale_schemas(out)
        if stale:
            typer.echo(f"Stale schemas: {', '.join(stale)}. Run `dink contracts export`.", err=True)
            raise typer.Exit(code=1)
        typer.echo("Schemas are current.")
        return
    for path in write_schemas(out):
        typer.echo(f"Wrote {path}")


class IdKind(StrEnum):
    video = "video"
    camera = "camera"
    facility = "facility"


@app.command(name="id")
def make_id(kind: IdKind) -> None:
    """Print the opaque id for a PickleCam id. Run with `uv run --env-file .env dink id video`.

    It asks for the PickleCam id at a hidden prompt, so the id stays out of shell history.
    """
    from dinkdata.contracts import ids

    try:
        key = ids.key_from_env(os.environ)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    raw = typer.prompt(f"PickleCam {kind.value} id", hide_input=True)
    make = {"video": ids.video_id, "camera": ids.camera_id, "facility": ids.facility_id}
    try:
        typer.echo(make[kind.value](raw, key))
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


@app.callback()
def main() -> None:
    """DinkData: turn PickleCam recordings into per-player stats and highlight reels."""


@app.command()
def version() -> None:
    """Print the installed dinkdata version."""
    typer.echo(_pkg_version("dinkdata"))


if __name__ == "__main__":
    app()
