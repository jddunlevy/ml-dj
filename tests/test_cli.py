from mldj.cli import main


def test_main_with_no_command_exits_two_and_prints_usage(capsys):
    assert main([]) == 2
    assert "usage: mldj" in capsys.readouterr().out
