import pytest

from mldj.cli import main


def test_main_with_no_command_exits_two_and_prints_usage(capsys):
    assert main([]) == 2
    assert "usage: mldj" in capsys.readouterr().out


def test_the_playlist_subcommand_is_registered_with_its_defaults():
    from mldj.cli import build_parser

    args = build_parser().parse_args(["playlist", "--session", "data/exports/s.json"])
    assert args.command == "playlist"
    assert (args.limit, args.per_artist, args.epsilon) == (30, 2, 0.0)
    assert (args.decay, args.w) == (0.85, 1.0)
    assert args.dry_run is False
    assert args.refresh_library is False


def test_playlist_run_raises_before_any_network_call_when_export_is_missing(tmp_path):
    """A missing --session file must fail fast, before load_env/token_provider/library IO.

    This is the one behaviour in playlist._run that is unit-testable without a token or
    network access: everything past the existence check reaches out to Spotify, Last.fm's
    cache, or the filesystem for real data. Pinning this guards against a refactor that
    moves the check after the network setup, which would turn a missing-file typo into a
    confusing auth or request failure instead of a clear message.
    """
    from argparse import Namespace

    from mldj.playlist import _run

    missing = tmp_path / "nope.json"
    args = Namespace(session=str(missing))
    with pytest.raises(SystemExit, match="no export at"):
        _run(args)


def test_the_queue_subcommand_is_registered():
    from mldj.cli import build_parser

    args = build_parser().parse_args(["queue", "--uri", "spotify:track:x"])
    assert args.command == "queue"
    assert args.uri == "spotify:track:x"
