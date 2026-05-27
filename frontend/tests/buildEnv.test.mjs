import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const frontendRoot = fileURLToPath(new URL('..', import.meta.url));
const scriptPath = join(frontendRoot, 'scripts', 'validateBuildEnv.mjs');

function runWithEnv(envPatch) {
  return spawnSync(process.execPath, [scriptPath], {
    cwd: frontendRoot,
    env: {
      ...process.env,
      VITE_API_URL: '',
      ...envPatch
    },
    encoding: 'utf8'
  });
}

const missing = runWithEnv({});
assert.equal(missing.status, 1);
assert.match(missing.stderr, /VITE_API_URL is required/);

const invalid = runWithEnv({ VITE_API_URL: 'not-a-url' });
assert.equal(invalid.status, 1);
assert.match(invalid.stderr, /valid absolute URL/);

const valid = runWithEnv({ VITE_API_URL: 'http://127.0.0.1:8000' });
assert.equal(valid.status, 0);
