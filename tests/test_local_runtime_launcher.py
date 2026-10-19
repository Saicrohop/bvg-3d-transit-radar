"""Exercise the npm entrypoint in scratch; block unsafe tools before execution."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

# This controlled preload observes npm and the launcher, not malicious host tools.
NODE_GUARD = r'''
const fs = require('node:fs');
const cp = require('node:child_process');
const audit = process.env.PREFLIGHT_NODE_AUDIT;
const append = fs.appendFileSync.bind(fs);
function record(entry) { append(audit, JSON.stringify(entry) + '\n'); }
function forbidden(kind, value) {
  record({kind, value: String(value)});
  throw new Error('fixture blocked unsafe preflight operation');
}
for (const name of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync']) {
  const original = cp[name];
  cp[name] = function(...args) {
    const command = String(args[0]) + ' ' + JSON.stringify(args[1] || []);
    if (/\b(?:uv|docker|supabase|pip|curl|wget)(?:\.(?:exe|cmd))?\b/i.test(command)) {
      forbidden('forbidden_process', command);
    }
    const childEnvironment = args[2]?.env || process.env;
    const pythonChild = String(args[0]).toLowerCase().includes('python');
    record({
      kind: 'process',
      command,
      pythonChild,
      inheritedSensitiveEnvironment: pythonChild
        ? Object.keys(childEnvironment).filter(name => /^(?:BVG_|DATABASE_|POSTGRES_|PG(?:_|$)|SUPABASE_|.*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|CREDENTIAL|AUTHORIZATION).*)/i.test(name))
        : [],
    });
    return original.apply(this, args);
  };
}
function checkFile(file) {
  if (String(file).replaceAll('\\', '/').split('/').at(-1) === '.env') {
    forbidden('env_read', file);
  }
}
for (const name of ['readFile', 'readFileSync', 'open', 'openSync']) {
  const original = fs[name];
  fs[name] = function(file, ...args) { checkFile(file); return original.call(this, file, ...args); };
}
for (const name of ['readFile', 'open']) {
  const original = fs.promises[name];
  fs.promises[name] = function(file, ...args) { checkFile(file); return original.call(this, file, ...args); };
}
require('node:net').Socket.prototype.connect = function() { forbidden('network', 'net.connect'); };
for (const protocol of ['node:http', 'node:https']) {
  for (const method of ['get', 'request']) {
    require(protocol)[method] = function() { forbidden('network', protocol + '.' + method); };
  }
}
'''


def snapshot(root):
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def launcher_project(tmp_path):
    root = tmp_path / 'project'
    for name in ['scripts', 'src/bvg_radar', 'supabase']:
        (root / name).mkdir(parents=True, exist_ok=True)
    scripts = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['scripts']
    (root / 'package.json').write_text(json.dumps({'name': 'preflight-fixture', 'scripts': {
        'runtime:check': scripts['runtime:check'],
    }}), encoding='utf-8')
    for name in ['scripts/check_local_runtime.py', 'scripts/check_local_runtime.cjs',
                 'src/bvg_radar/local_runtime.py', 'supabase/config.toml']:
        if (ROOT / name).is_file():
            shutil.copyfile(ROOT / name, root / name)
    for name in ['uv.lock', 'package-lock.json', 'pyproject.toml', '.env']:
        (root / name).write_text('fixture-marker-must-not-be-read-or-replaced\n', encoding='utf-8')
    guard = tmp_path / 'node-guard.cjs'
    guard.write_text(NODE_GUARD, encoding='utf-8')
    python_audit = tmp_path / 'python-audit.jsonl'
    # Installed at the first project import, before local_runtime imports/probes.
    (root / 'src/bvg_radar/__init__.py').write_text('''import sys
import json
_auditing = False
def _audit(event, args):
    global _auditing
    blocked = (event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.exec', 'os.posix_spawn')
               or (event == 'open' and str(args[0]).replace('\\\\', '/').split('/')[-1] == '.env')
               or (event == 'import' and str(args[0]).split('.')[0] in ('asyncpg', 'aiohttp', 'fastapi', 'uvicorn', 'dotenv')))
    if blocked and not _auditing:
        _auditing = True
        with open(''' + repr(str(python_audit)) + ''', 'a', encoding='utf-8') as log:
            log.write(json.dumps({'event': event, 'args': str(args)}) + '\\n')
        _auditing = False
        raise RuntimeError('fixture blocked unsafe Python operation')
sys.addaudithook(_audit)
''', encoding='utf-8')
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('BVG_', 'PG', 'DATABASE_', 'UV_', 'PYTHON', 'NODE_OPTIONS', 'NPM_CONFIG_'))}
    for key in tuple(env):
        if key.upper() in {'PROGRAMFILES', 'PROGRAMW6432', 'PROGRAMFILES(X86)'}:
            env.pop(key)
    env.update(UV_ENV_FILE=str(root / '.env'), PYTHONPATH=str(root / 'poison'),
               PYTHONSTARTUP=str(root / 'poison/sitecustomize.py'),
               NODE_OPTIONS='--require=' + str(guard), PREFLIGHT_NODE_AUDIT=str(tmp_path / 'node-audit.jsonl'),
               BVG_DATABASE_URL='fixture-dsn-not-real', PGHOST='fixture-host',
               PGPASSWORD='fixture-password-not-real', DATABASE_URL='fixture-url-not-real',
               SUPABASE_ACCESS_TOKEN='fixture-token-not-real', OPENAI_API_KEY='fixture-key-not-real',
               ProgramFiles=str(tmp_path / 'no-programs'),
               ProgramW6432=str(tmp_path / 'no-programs'),
               **{'ProgramFiles(x86)': str(tmp_path / 'no-programs')},
               npm_config_offline='true', npm_config_audit='false', npm_config_fund='false',
               npm_config_update_notifier='false', npm_config_cache=str(tmp_path / 'npm-cache'))
    # Discovery is fixture-only even on a host that later gains Docker.
    node = shutil.which('node')
    assert node, 'Tests require pre-provisioned Node'
    system = Path(os.environ.get('SystemRoot', '/')) / 'System32' if os.name == 'nt' else Path('/usr/bin')
    env['PATH'] = os.pathsep.join([str(Path(node).parent), str(system)])
    env['PYTHONHOME'] = str(tmp_path / 'must-not-use-python-home')
    env['UV_PROJECT_ENVIRONMENT'] = str(tmp_path / 'must-not-create-uv-environment')
    poison = root / 'poison'
    poison.mkdir()
    (poison / 'sitecustomize.py').write_text("raise RuntimeError('PYTHONPATH/site must be ignored')\n", encoding='utf-8')
    return root, env


def provision_python(root):
    # Copy only the already-provisioned interpreter and its existing base pointer.
    directory = root / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')
    directory.mkdir(parents=True)
    target = directory / ('python.exe' if os.name == 'nt' else 'python')
    shutil.copy2(sys.executable, target)
    config = Path(sys.prefix) / 'pyvenv.cfg'
    if config.is_file():
        shutil.copyfile(config, root / '.venv/pyvenv.cfg')
    site = root / '.venv' / ('Lib/site-packages' if os.name == 'nt' else 'lib/python%d.%d/site-packages' % sys.version_info[:2])
    site.mkdir(parents=True)
    (site / 'sitecustomize.py').write_text("raise RuntimeError('site must be disabled')\n", encoding='utf-8')
    (site / 'poison.pth').write_text("import sys; sys.exit('pth must be disabled')\n", encoding='utf-8')
    return target


def run_npm(root, env):
    node = shutil.which('node')
    npm = shutil.which('npm')
    assert node and npm, 'Tests require pre-provisioned Node/npm; never install'
    candidates = [Path(npm).parent / 'node_modules/npm/bin/npm-cli.js',
                  Path(npm).resolve().parent / 'npm-cli.js']
    cli = next((path for path in candidates if path.is_file()), None)
    assert cli is not None, 'Cannot locate the pre-provisioned npm CLI'
    command = [node, str(cli), '--offline', '--silent', 'run', 'runtime:check']
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    audit = Path(env['PREFLIGHT_NODE_AUDIT'])
    entries = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()] if audit.exists() else []
    receipt = {'command': command, 'cwd': str(root), 'returncode': result.returncode,
               'stdout': result.stdout, 'stderr': result.stderr, 'node_audit': entries,
               'python_unsafe_operations': (root.parent / 'python-audit.jsonl').read_text(encoding='utf-8')
                   if (root.parent / 'python-audit.jsonl').exists() else ''}
    (root.parent / 'runner-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    assert not [entry for entry in entries if entry['kind'] != 'process'], receipt
    assert receipt['python_unsafe_operations'] == '', receipt
    return result, entries


def test_npm_runner_uses_only_provisioned_python_without_envfile_or_preparation(launcher_project):
    root, env = launcher_project
    provision_python(root)
    before = snapshot(root)
    result, entries = run_npm(root, env)
    assert result.returncode == 2, (result.stdout, result.stderr)
    report = json.loads(result.stdout)
    assert report['status'] == 'blocked'
    assert report['blockers'] == ['docker_cli_missing', 'supabase_project_cli_missing']
    assert report['port_checks'] == []
    assert report['configured_ports'] == {'api': 55030, 'db': 55031, 'studio': 55032, 'local_smtp': 55033}
    assert report['live_gate'] == 'not_run'
    assert result.stderr == ''
    assert len(entries) == 2  # npm shell, then the one existing Python interpreter.
    assert entries[-1]["pythonChild"] is True
    assert entries[-1]["inheritedSensitiveEnvironment"] == []
    assert '-I' in entries[-1]['command'] and '-S' in entries[-1]['command'] and '-B' in entries[-1]['command']
    assert snapshot(root) == before  # Includes locks, interpreter tree and no bytecode.
    assert not Path(env['UV_PROJECT_ENVIRONMENT']).exists()


def test_npm_runner_missing_project_python_fails_without_creating_environment(launcher_project):
    root, env = launcher_project
    before = snapshot(root)
    result, entries = run_npm(root, env)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        'status': 'blocked', 'blockers': ['project_python_missing'], 'live_gate': 'not_run',
    }
    assert result.stderr == ''
    assert len(entries) == 1  # npm's local shell only; no Python/uv fallback.
    assert not (root / '.venv').exists()
    assert not Path(env['UV_PROJECT_ENVIRONMENT']).exists()
    assert snapshot(root) == before


@pytest.mark.parametrize('problem', ['unlaunchable', 'bootstrap_failure', 'checker_missing'])
def test_npm_runner_python_failures_are_sanitized(launcher_project, problem):
    root, env = launcher_project
    python = provision_python(root)
    if problem == 'unlaunchable':
        python.write_text('private-executable-marker', encoding='utf-8')
    elif problem == 'checker_missing':
        (root / 'scripts/check_local_runtime.py').unlink()
    else:
        (root / 'src/bvg_radar/local_runtime.py').unlink()
    before = snapshot(root)
    result, entries = run_npm(root, env)
    assert result.returncode == 2
    assert result.stderr == ''
    assert json.loads(result.stdout) == {
        'status': 'blocked', 'blockers': ['project_python_failed'], 'live_gate': 'not_run',
    }
    assert 'private-executable-marker' not in result.stdout
    assert str(root) not in result.stdout
    assert len(entries) == 2
    assert snapshot(root) == before
