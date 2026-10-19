"""Offline discovery only: never execute CLIs, start services or query a database."""
from collections.abc import Callable
from datetime import UTC, datetime
import errno
import os
from pathlib import Path
import shutil
import socket
import tomllib

APPROVED_PORTS = {'api': 55030, 'db': 55031, 'studio': 55032, 'local_smtp': 55033}
PROJECT_ID = 'bvg-3d-radar'


def probe_local_port(port: int) -> dict[str, object]:
    if type(port) is not int or port not in APPROVED_PORTS.values():
        raise ValueError('Only approved project ports may be probed')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.15)
        connect_result = connection.connect_ex(('127.0.0.1', port))
        if connect_result not in (0, errno.ECONNREFUSED):
            raise OSError('Local connection probe unavailable')
        listening = connect_result == 0
    available = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as binding:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            binding.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            binding.bind(('127.0.0.1', port))
            available = True
        except OSError:
            pass
    return {'listening': listening, 'bind_available': available}


def _docker_cli(find_executable: Callable[[str], str | None]) -> str | None:
    executable = find_executable('docker')
    if executable:
        return executable
    if os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/resources/bin/docker.exe'
        if candidate.is_file():
            return str(candidate)
    return None


def _project_supabase_cli(root: Path) -> str | None:
    for name in ('supabase.cmd', 'supabase.exe', 'supabase'):
        candidate = root / 'node_modules/.bin' / name
        if candidate.is_file():
            return str(candidate)
    return None


def _approved_ports(root: Path) -> dict[str, int]:
    config = tomllib.loads((root / 'supabase/config.toml').read_text(encoding='utf-8'))
    if config.get('project_id') != PROJECT_ID:
        raise ValueError('Unexpected project')
    ports = {name: config[name]['port'] for name in APPROVED_PORTS}
    if any(type(port) is not int or port != APPROVED_PORTS[name] for name, port in ports.items()):
        raise ValueError('Unexpected local port contract')
    return ports


def _report(ports, blockers, docker=None, supabase=None, port_checks=None):
    return {
        'observed_at': datetime.now(UTC).isoformat(),
        'status': 'blocked' if blockers else 'offline_checks_passed',
        'configured_ports': ports,
        'blockers': blockers,
        'docker_cli': docker,
        'supabase_project_cli': supabase,
        'port_checks': port_checks or [],
        'live_gate': 'not_run',
        'docker_daemon': 'not_inspected',
        'volumes': 'not_inspected',
        'database': 'not_queried',
        'gtfs': 'not_inspected',
        'forwarding_verified': False,
    }


def inspect_local_runtime(
    root: Path,
    *,
    find_executable: Callable[[str], str | None] | None = None,
    port_probe: Callable[[int], dict[str, object]] | None = None,
) -> dict[str, object]:
    try:
        ports = _approved_ports(root)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return _report({}, ['local_config_invalid'])
    try:
        docker = _docker_cli(find_executable or shutil.which)
        supabase = _project_supabase_cli(root)
    except OSError:
        return _report(ports, ['tool_discovery_failed'])
    blockers = []
    if docker is None:
        blockers.append('docker_cli_missing')
    if supabase is None:
        blockers.append('supabase_project_cli_missing')
    if blockers:
        return _report(ports, blockers, docker, supabase)
    probe = port_probe or probe_local_port
    checks = []
    for service, port in ports.items():
        try:
            state = probe(port)
        except OSError:
            state = {'listening': False, 'bind_available': False, 'probe_error': 'socket_error'}
            blockers.append(f'port_probe_failed:{service}')
        else:
            if state['listening'] or not state['bind_available']:
                blockers.append(f'port_unavailable:{service}')
        checks.append({'service': service, 'port': port, **state})
    return _report(ports, blockers, docker, supabase, checks)
