import pytest

from mldj.env import load_env, parse_env, require


def test_parse_env_reads_simple_pairs():
    assert parse_env("SPOTIFY_CLIENT_ID=abc123\n") == {"SPOTIFY_CLIENT_ID": "abc123"}


def test_parse_env_ignores_comments_and_blank_lines():
    text = "# this repo is public\n\nLASTFM_API_KEY=key\n"
    assert parse_env(text) == {"LASTFM_API_KEY": "key"}


def test_parse_env_strips_matched_quotes():
    assert parse_env('LASTFM_USER="jaxon"\n') == {"LASTFM_USER": "jaxon"}
    assert parse_env("LASTFM_USER='jaxon'\n") == {"LASTFM_USER": "jaxon"}


def test_parse_env_keeps_equals_signs_inside_the_value():
    assert parse_env("TOKEN=ab=cd\n") == {"TOKEN": "ab=cd"}


def test_parse_env_keeps_an_empty_value():
    assert parse_env("LASTFM_USER=\n") == {"LASTFM_USER": ""}


def test_load_env_returns_empty_dict_when_the_file_is_absent(tmp_path):
    assert load_env(tmp_path / "nope.local") == {}


def test_load_env_reads_a_real_file(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text("SPOTIFY_CLIENT_ID=xyz\n", encoding="utf-8")
    assert load_env(path) == {"SPOTIFY_CLIENT_ID": "xyz"}


def test_require_returns_a_present_value():
    assert require({"LASTFM_USER": "jaxon"}, "LASTFM_USER") == "jaxon"


def test_require_rejects_a_missing_key():
    with pytest.raises(SystemExit):
        require({}, "LASTFM_API_KEY")


def test_require_rejects_an_empty_value():
    # .env.local.example ships LASTFM_USER= with no value, so empty must fail too.
    with pytest.raises(SystemExit):
        require({"LASTFM_USER": ""}, "LASTFM_USER")
