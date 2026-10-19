from pathlib import Path
import runpy
import tomllib

import pytest

from bvg_radar.realtime.benchmark import validate_local_database_url

ROOT = Path(__file__).resolve().parents[1]


def test_supabase_public_ports_match_the_approved_four_port_migration() -> None:
    config = tomllib.loads((ROOT / 'supabase/config.toml').read_text(encoding='utf-8'))
    assert {name: config[name]['port'] for name in ('api', 'db', 'studio', 'local_smtp')} == {
        'api': 55030, 'db': 55031, 'studio': 55032, 'local_smtp': 55033,
    }
    assert config['project_id'] == 'bvg-3d-radar'
    assert config['db']['shadow_port'] == 54020
    assert config['db']['pooler']['port'] == 54029
    assert config['db']['pooler']['enabled'] is False
    assert config['analytics']['port'] == 54027
    assert config['edge_runtime']['inspector_port'] == 8083


@pytest.mark.parametrize('host', ['127.0.0.1', 'localhost', '[::1]'])
def test_database_guard_accepts_only_the_new_project_port(host: str) -> None:
    accepted = f'postgresql://fixture-user:fixture-pass@{host}:55031/postgres'
    assert validate_local_database_url(accepted) == accepted
    with pytest.raises(ValueError):
        validate_local_database_url(accepted.replace(':55031/', ':54022/'))


@pytest.mark.parametrize('value', [
    None, False, 123, {}, [],
    'postgresql://fixture-user:fixture-pass@127.0.0.1:not-a-port-marker/postgres',
    'postgresql://fixture-user:fixture-pass@[::1:55031/postgres',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres?host=example.com',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres?port=5432',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres;override',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres#fragment',
    'postgresql://fixture-user:fixture-pass@example.com:55031/postgres',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55030/postgres',
    'postgresql://fixture-user:fixture-pass@127.0.0.1/postgres',
    'https://fixture-user:fixture-pass@127.0.0.1:55031/postgres',
])
def test_invalid_database_urls_fail_closed_without_echoing_input(value: object) -> None:
    with pytest.raises(ValueError) as error:
        validate_local_database_url(value)
    assert str(error.value) == 'database must be PostgreSQL on project-local loopback port 55031 without URL overrides'
    assert 'not-a-port-marker' not in str(error.value)
    assert 'fixture-pass' not in str(error.value)


@pytest.fixture(scope='module')
def integration_url_guard():
    return runpy.run_path(str(ROOT / 'tests/integration/test_realtime_postgis.py'))['_local_database_url']


def test_integration_accepts_the_same_new_port_without_connecting(monkeypatch, integration_url_guard) -> None:
    url = 'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres'
    monkeypatch.setenv('BVG_DATABASE_URL', url)
    assert integration_url_guard() == url


@pytest.mark.parametrize('url', [
    'postgresql://fixture-user:fixture-pass@127.0.0.1:54022/postgres',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres?host=example.com',
    'postgresql://fixture-user:fixture-pass@127.0.0.1:55031/postgres?port=5432',
])
def test_integration_rejects_old_or_redirected_urls_before_connecting(monkeypatch, integration_url_guard, url) -> None:
    monkeypatch.setenv('BVG_DATABASE_URL', url)
    with pytest.raises(pytest.fail.Exception):
        integration_url_guard()


def test_integration_missing_configuration_still_skips_without_connecting(monkeypatch, integration_url_guard) -> None:
    monkeypatch.delenv('BVG_DATABASE_URL', raising=False)
    with pytest.raises(pytest.skip.Exception):
        integration_url_guard()
