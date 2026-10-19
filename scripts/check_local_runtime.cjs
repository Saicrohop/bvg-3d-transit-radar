// Use only the existing project interpreter: never ask uv to prepare one.
const { statSync } = require('node:fs');
const { resolve, join } = require('node:path');
const { spawnSync } = require('node:child_process');

const root = resolve(__dirname, '..');
const python = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

function blocked(reason) {
  console.log(JSON.stringify({ status: 'blocked', blockers: [reason], live_gate: 'not_run' }));
  process.exit(2);
}

try {
  if (!statSync(python).isFile()) blocked('project_python_missing');
} catch {
  blocked('project_python_missing');
}

const SAFE_CHILD_ENVIRONMENT = new Set([
  'PATH', 'PATHEXT', 'COMSPEC', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE',
  'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'LOCALAPPDATA',
  'PROGRAMDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME',
  'TEMP', 'TMP', 'TMPDIR',
]);
const env = Object.fromEntries(Object.entries(process.env).filter(
  ([name]) => SAFE_CHILD_ENVIRONMENT.has(name.toUpperCase()),
));
const child = spawnSync(python, [
  '-I', '-S', '-B', join(root, 'scripts/check_local_runtime.py'), ...process.argv.slice(2),
], { cwd: root, env, encoding: 'utf8', windowsHide: true });

if (child.error || child.signal || child.stderr || !child.stdout || ![0, 2].includes(child.status)) {
  blocked('project_python_failed');
}
process.stdout.write(child.stdout);
process.exitCode = child.status;
