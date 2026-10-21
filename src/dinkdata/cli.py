"""The `dink` command-line tool.

Each subcommand is built in its own ticket (docs/DESIGN.md section 14). Until then it prints
"not built yet" and exits with code 1, so scripts never mistake a placeholder for real work.
"""

import os
from enum import StrEnum
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated, cast

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


@contracts_app.command("upgrade-rallies")
def contracts_upgrade_rallies(
    labels: Annotated[Path, typer.Option(help="Local folder for label files.")] = Path("labels"),
) -> None:
    """Save each labeller's latest v1 rallies.json as a new v2 version. Nothing is overwritten."""
    import json

    from dinkdata.contracts.common import to_json
    from dinkdata.contracts.rallies import upgrade_v1
    from dinkdata.studio import store

    upgraded = 0
    for folder in sorted((labels / store.GOLD_RALLIES).glob("*/*")):
        path = store.latest(folder, ".json")
        if path is None or json.loads(path.read_text()).get("schema") != "dinkdata.rallies/v1":
            continue
        new = store.write_new_version(
            folder, to_json(upgrade_v1(json.loads(path.read_text()))).encode(), ".json"
        )
        typer.echo(f"Upgraded {path} to {new.name}. Re-check its winners in the labeller.")
        upgraded += 1
    typer.echo(f"Upgraded {upgraded} file(s).")


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


class SplitChoice(StrEnum):
    train = "train"
    dev = "dev"
    test = "test"


@app.command()
def ingest(
    video: Annotated[
        Path, typer.Argument(help="The downloaded MP4. Rename it first if its name has an id.")
    ],
    split: Annotated[
        SplitChoice | None,
        typer.Option(help="Split for a game from a new facility.", show_default=False),
    ] = None,
    videos: Annotated[
        Path, typer.Option(help="Local folder for the prepared video, as the studio reads it.")
    ] = Path("data/videos"),
) -> None:
    """Prepare one hand-downloaded game and upload it to R2.

    Run with `uv run --env-file .env dink ingest game.mp4`. It asks for the session id,
    facility and court at a hidden prompt, so they stay out of shell history and output.
    """
    from dinkdata.contracts import ids
    from dinkdata.contracts.common import Split
    from dinkdata.data import ingest as intake
    from dinkdata.data import r2
    from dinkdata.video import ffmpeg

    missing = intake.missing_tools()
    if missing:
        typer.echo(
            f"Missing {', '.join(missing)}. Install ffmpeg with `brew install ffmpeg` and "
            "rclone with scripts/r2-setup.sh.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        key = ids.key_from_env(os.environ)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    if not video.is_file():
        typer.echo("That video file doesn't exist.", err=True)
        raise typer.Exit(code=1)
    session_id = typer.prompt("PickleCam session id", hide_input=True, confirmation_prompt=True)
    facility = typer.prompt("Facility, as the dashboard names it", hide_input=True)
    court = typer.prompt("Court number", hide_input=True)
    secrets = [session_id, facility, str(video), video.name]
    try:
        game = intake.Game(session_id, facility, intake.parse_court(court))
        typer.echo("Checking every frame. A 15-minute game takes about 2 minutes.")
        report = intake.ingest(
            video, game, key, r2.RcloneStore(), videos, cast(Split, split.value) if split else None
        )
    except (ValueError, ffmpeg.FfmpegError, r2.RcloneError) as error:
        typer.echo(intake.redact(str(error), secrets), err=True)
        raise typer.Exit(code=1) from None

    where = "New facility" if report.new_facility else "Known facility"
    typer.echo(f"{where} {report.facility_id}, {report.split} split. Camera {report.camera_id}.")
    if report.already_ingested:
        typer.echo(f"{report.video_id} is already in R2 and the catalog. Nothing to do.")
        return
    typer.echo(f"{report.frames} frames, {report.dropped} dropped, {report.duplicates} duplicated.")
    for path in report.uploaded:
        typer.echo(f"Uploaded {path}")
    typer.echo(report.video_id)


@app.command()
def studio(
    rallies: Annotated[
        str | None,
        typer.Option(
            help="Video id to label in rally mode, from `dink id video`.", show_default=False
        ),
    ] = None,
    labeller: Annotated[str | None, typer.Option(help="Your short handle, such as marti.")] = None,
    videos: Annotated[
        Path, typer.Option(help="Local folder of videos named <video_id>.mp4, as in R2.")
    ] = Path("data/videos"),
    labels: Annotated[Path, typer.Option(help="Local folder for label files.")] = Path("labels"),
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1.")] = 8765,
) -> None:
    """Open the labelling and review studio. Only rally mode is built so far.

    Videos are found by id, so a file name with a session id never reaches the command line.
    """
    if rallies is None or labeller is None:
        typer.echo(
            "Only rally mode is built: dink studio --rallies <video_id> --labeller <handle>",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        import uvicorn

        from dinkdata.studio.server import create_app
    except ImportError:
        typer.echo("The studio needs its extra: uv sync --extra studio", err=True)
        raise typer.Exit(code=1) from None
    try:
        studio_app = create_app(videos / f"{rallies}.mp4", rallies, labeller, labels)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Rally mode for {rallies}: http://127.0.0.1:{port}")
    uvicorn.run(studio_app, host="127.0.0.1", port=port)


@app.callback()
def main() -> None:
    """DinkData: turn PickleCam recordings into per-player stats and highlight reels."""


@app.command()
def version() -> None:
    """Print the installed dinkdata version."""
    typer.echo(_pkg_version("dinkdata"))


if __name__ == "__main__":
    app()
