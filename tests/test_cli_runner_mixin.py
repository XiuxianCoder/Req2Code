from req2code.runners.cli_runner_mixin import CliRunnerMixin


class _Dummy(CliRunnerMixin):
    pass


def test_render_command_replaces_placeholders():
    mix = _Dummy()
    cmd = mix._render_command("echo {name}", {"name": "world"})
    assert cmd == "echo world"
