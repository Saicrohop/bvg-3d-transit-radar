import errno
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[1] / 'scripts/check_local_runtime.py'
    spec = importlib.util.spec_from_file_location('local_runtime_cli_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('status,exit_code', [('blocked', 2), ('offline_checks_passed', 0)])
def test_json_cli_preserves_report_and_explicit_exit_codes(cli, monkeypatch, capsys, status, exit_code):
    report = {'status': status, 'blockers': ['fixture'] if exit_code else [], 'live_gate': 'not_run'}
    monkeypatch.setattr(cli, 'inspect_local_runtime', lambda _root: report)
    assert cli.main(['--json']) == exit_code
    assert json.loads(capsys.readouterr().out) == report


def test_cli_does_not_offer_an_automatic_start_or_reset(cli, monkeypatch):
    def forbidden(*_args):
        raise AssertionError('Invalid command must not run discovery or services')

    monkeypatch.setattr(cli, 'inspect_local_runtime', forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(['--start'])
    assert error.value.code == 2


def test_human_output_never_presents_offline_checks_as_live_success(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'inspect_local_runtime', lambda _root: {
        'status': 'offline_checks_passed', 'blockers': [], 'live_gate': 'not_run',
    })
    assert cli.main([]) == 0
    text = capsys.readouterr().out
    assert 'Live gate: not_run' in text
    assert 'not a database or Docker-daemon validation' in text


@pytest.mark.parametrize('connect_result,exit_code,blocker', [
    (errno.ECONNREFUSED, 0, None),
    (0, 2, 'port_unavailable'),
    (13, 2, 'port_probe_failed'),
    (10013, 2, 'port_probe_failed'),
    (10060, 2, 'port_probe_failed'),
    (424242, 2, 'port_probe_failed'),
    ('exception', 2, 'port_probe_failed'),
])
def test_json_cli_classifies_socket_returns_and_exceptions(cli, tmp_path, monkeypatch, capsys,
                                                         connect_result, exit_code, blocker):
    import bvg_radar.local_runtime as runtime

    config = tmp_path / 'supabase/config.toml'
    config.parent.mkdir()
    source = Path(__file__).resolve().parents[1] / 'supabase/config.toml'
    config.write_bytes(source.read_bytes())
    entrypoint = tmp_path / 'node_modules/.bin/supabase.cmd'
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text('fixture-only; never execute', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr(runtime, '_docker_cli', lambda _find: 'fixture-docker')
    sockets = []
    binds = []

    class FakeSocket:
        closed = False

        def __enter__(self):
            sockets.append(self)
            return self

        def __exit__(self, *_args):
            self.closed = True

        def settimeout(self, _timeout):
            pass

        def setsockopt(self, *_args):
            pass

        def connect_ex(self, address):
            assert address[0] == '127.0.0.1' and address[1] in (55030, 55031, 55032, 55033)
            if connect_result == 'exception':
                raise OSError(13, 'private-connect-marker')
            return connect_result

        def bind(self, address):
            binds.append(address)  # Success must not rescue an unknown connect_ex code.

    monkeypatch.setattr(runtime.socket, 'socket', lambda *_args: FakeSocket())
    assert cli.main(['--json']) == exit_code
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report['status'] == ('offline_checks_passed' if exit_code == 0 else 'blocked')
    assert report['blockers'] == ([f'{blocker}:{name}' for name in runtime.APPROVED_PORTS] if blocker else [])
    assert report['live_gate'] == 'not_run'
    assert report['docker_daemon'] == 'not_inspected'
    assert report['volumes'] == 'not_inspected'
    assert report['database'] == 'not_queried'
    assert report['gtfs'] == 'not_inspected'
    assert report['forwarding_verified'] is False
    assert all(item.closed for item in sockets)
    assert len(sockets) == (8 if connect_result in (0, errno.ECONNREFUSED) else 4)
    assert len(binds) == (4 if connect_result in (0, errno.ECONNREFUSED) else 0)
    assert 'private-connect-marker' not in output.out
    assert output.err == ''
