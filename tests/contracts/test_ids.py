import hashlib
import hmac
import re

import pytest
from typer.testing import CliRunner

from dinkdata.cli import app
from dinkdata.contracts.ids import ID_KEY_ENV, camera_id, facility_id, key_from_env, video_id

KEY = b"synthetic-test-key-not-a-real-secret"
SESSION = "synthetic-session-0001"


def test_video_id_is_a_truncated_hmac_sha256():
    expected = hmac.new(KEY, SESSION.encode(), hashlib.sha256).hexdigest()[:16]
    assert video_id(SESSION, KEY) == f"v_{expected}"


def test_ids_are_stable_and_depend_on_the_key():
    assert video_id(SESSION, KEY) == video_id(SESSION, KEY)
    assert video_id(SESSION, KEY) != video_id(SESSION, KEY + b"x")


def test_each_kind_of_id_has_its_prefix():
    assert re.fullmatch(r"v_[0-9a-f]{16}", video_id(SESSION, KEY))
    assert re.fullmatch(r"c_[0-9a-f]{16}", camera_id("cam-1", KEY))
    assert re.fullmatch(r"f_[0-9a-f]{16}", facility_id("fac-1", KEY))


def test_empty_raw_id_is_an_error():
    with pytest.raises(ValueError):
        video_id("  ", KEY)


def test_key_from_env():
    assert key_from_env({ID_KEY_ENV: KEY.decode()}) == KEY


@pytest.mark.parametrize("environ", [{}, {ID_KEY_ENV: ""}, {ID_KEY_ENV: "short"}])
def test_key_from_env_rejects_missing_or_short_keys(environ):
    with pytest.raises(ValueError, match=ID_KEY_ENV):
        key_from_env(environ)


runner = CliRunner()


def test_cli_prints_only_the_id():
    result = runner.invoke(
        app, ["id", "video"], input=f"{SESSION}\n", env={ID_KEY_ENV: KEY.decode()}
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines()[-1] == video_id(SESSION, KEY)
    assert SESSION not in result.output


def test_cli_without_a_key_fails_and_says_how_to_set_it():
    result = runner.invoke(app, ["id", "video"], input=f"{SESSION}\n", env={ID_KEY_ENV: ""})
    assert result.exit_code == 1
    assert ID_KEY_ENV in result.output
