import errno
from pathlib import Path

import pytest

import bvg_radar.local_runtime as runtime
from bvg_radar.local_runtime import inspect_local_runtime


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'programs'))
    monkeypatch.setenv('BVG_DATABASE_URL', 'must-not-appear-in-diagnostics')
    config = tmp_path / 'supabase/config.toml'
    config.parent.mkdir()
    config.write_text('''project_id = "bvg-3d-radar"
[api]
port = 55030
[db]
port = 55031
[studio]
port = 55032
[local_smtp]
port = 55033
''', encoding='utf-8')
    return tmp_path


def test_missing_tools_block_without_running_commands_or_probing_ports(project):
    def forbidden_probe(_port):
        raise AssertionError('Do not probe ports before prerequisites exist')

    report = inspect_local_runtime(
        project, find_executable=lambda _name: None, port_probe=forbidden_probe,
    )
    assert report['status'] == 'blocked'
    assert report['blockers'] == ['docker_cli_missing', 'supabase_project_cli_missing']
    assert report['configured_ports'] == {'api': 55030, 'db': 55031, 'studio': 55032, 'local_smtp': 55033}
    assert report['port_checks'] == []
    assert report['live_gate'] == 'not_run'
    assert report['volumes'] == 'not_inspected'
    assert 'must-not-appear-in-diagnostics' not in str(report)


@pytest.mark.parametrize('problem', ['missing', 'malformed', 'encoding', 'project', 'port', 'boolean_port', 'missing_section'])
def test_invalid_config_blocks_before_any_discovery_or_network(project, problem):
    config = project / 'supabase/config.toml'
    text = config.read_text(encoding='utf-8')
    if problem == 'missing':
        config.unlink()
    elif problem == 'malformed':
        config.write_text('invalid = [private-config-marker', encoding='utf-8')
    elif problem == 'encoding':
        config.write_bytes(b'\xff')
    elif problem == 'project':
        config.write_text(text.replace('bvg-3d-radar', 'different-project'), encoding='utf-8')
    elif problem == 'port':
        config.write_text(text.replace('55031', '55034'), encoding='utf-8')
    elif problem == 'boolean_port':
        config.write_text(text.replace('55031', 'true'), encoding='utf-8')
    else:
        config.write_text(text.replace('[db]', '[other]'), encoding='utf-8')

    def forbidden(*_args):
        raise AssertionError('Invalid config must not reach dependency or port discovery')

    report = inspect_local_runtime(project, find_executable=forbidden, port_probe=forbidden)
    assert report['status'] == 'blocked'
    assert report['blockers'] == ['local_config_invalid']
    assert report['configured_ports'] == {}
    assert 'private-config-marker' not in str(report)


def fixture_supabase_cli(project):
    entrypoint = project / 'node_modules/.bin/supabase.cmd'
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text('fixture-only; never execute', encoding='utf-8')
    return entrypoint


def test_available_tools_and_free_ports_only_pass_offline_checks(project):
    fixture_supabase_cli(project)
    observed = []

    def probe(port):
        observed.append(port)
        return {'listening': False, 'bind_available': True}

    report = inspect_local_runtime(project, find_executable=lambda _name: 'fixture-docker', port_probe=probe)
    assert observed == [55030, 55031, 55032, 55033]
    assert report['status'] == 'offline_checks_passed'
    assert report['blockers'] == []
    assert len(report['port_checks']) == 4
    assert report['live_gate'] == 'not_run'
    assert report['docker_daemon'] == 'not_inspected'
    assert report['forwarding_verified'] is False


@pytest.mark.parametrize('listening,bind_error', [(False, False), (True, True), (False, True)])
def test_socket_probe_only_uses_loopback_and_releases_each_socket(monkeypatch, listening, bind_error):
    sockets = []
    addresses = []

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
            addresses.append(address)
            return 0 if listening else errno.ECONNREFUSED

        def bind(self, address):
            addresses.append(address)
            if bind_error:
                raise OSError(13, 'do-not-expose-socket-error')

    import socket
    monkeypatch.setattr(socket, 'socket', lambda *_args: FakeSocket())
    state = runtime.probe_local_port(55031)
    assert state['listening'] is listening
    assert state['bind_available'] is not bind_error
    assert addresses == [('127.0.0.1', 55031), ('127.0.0.1', 55031)]
    assert len(sockets) == 2 and all(item.closed for item in sockets)
    assert 'do-not-expose-socket-error' not in str(state)


def test_probe_rejects_unapproved_port_before_socket_creation(monkeypatch):
    import socket

    def forbidden(*_args):
        raise AssertionError('Unapproved port must never be probed')

    monkeypatch.setattr(socket, 'socket', forbidden)
    with pytest.raises(ValueError):
        runtime.probe_local_port(55034)


@pytest.mark.parametrize('problem', ['occupied', 'permission', 'socket_error'])
def test_occupied_or_uninspectable_ports_block_without_exposing_errors(project, problem):
    fixture_supabase_cli(project)

    def probe(port):
        if port != 55031:
            return {'listening': False, 'bind_available': True}
        if problem == 'socket_error':
            raise OSError(13, 'private-socket-marker')
        return {'listening': problem == 'occupied', 'bind_available': False}

    report = inspect_local_runtime(project, find_executable=lambda _name: 'fixture-docker', port_probe=probe)
    expected = 'port_probe_failed:db' if problem == 'socket_error' else 'port_unavailable:db'
    assert report['status'] == 'blocked'
    assert report['blockers'] == [expected]
    assert len(report['port_checks']) == 4
    assert 'private-socket-marker' not in str(report)


@pytest.mark.parametrize('connect_code', [13, 10013, 10060, errno.ETIMEDOUT, 424242])
def test_connect_ex_error_return_blocks_even_when_bind_would_succeed(project, monkeypatch, connect_code):
    fixture_supabase_cli(project)
    sockets = []
    bound_addresses = []

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
            assert address[0] == '127.0.0.1'
            assert address[1] in (55030, 55031, 55032, 55033)
            return connect_code

        def bind(self, address):
            bound_addresses.append(address)  # Would succeed if incorrectly reached.

    monkeypatch.setattr(runtime.socket, 'socket', lambda *_args: FakeSocket())
    report = inspect_local_runtime(project, find_executable=lambda _name: 'fixture-docker')
    assert report['status'] == 'blocked'
    assert report['blockers'] == [f'port_probe_failed:{name}' for name in runtime.APPROVED_PORTS]
    assert all(check['probe_error'] == 'socket_error' for check in report['port_checks'])
    assert report['live_gate'] == 'not_run'
    assert len(sockets) == 4 and all(item.closed for item in sockets)
    assert bound_addresses == []


def test_tool_discovery_io_failure_is_sanitized_and_blocks_port_probes(project):
    def failing_discovery(_name):
        raise OSError(13, 'private-discovery-marker')

    def forbidden_probe(_port):
        raise AssertionError('No port probe after failed tool discovery')

    report = inspect_local_runtime(project, find_executable=failing_discovery, port_probe=forbidden_probe)
    assert report['status'] == 'blocked'
    assert report['blockers'] == ['tool_discovery_failed']
    assert report['port_checks'] == []
    assert 'private-discovery-marker' not in str(report)
