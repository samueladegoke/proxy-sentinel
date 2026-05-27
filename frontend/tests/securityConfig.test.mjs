import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const frontendRoot = fileURLToPath(new URL('..', import.meta.url));
const appSource = readFileSync(join(frontendRoot, 'src', 'App.jsx'), 'utf8');
const apiConfigSource = readFileSync(join(frontendRoot, 'src', 'lib', 'apiConfig.js'), 'utf8');

assert.doesNotMatch(
  appSource,
  /VITE_.*(?:TOKEN|SECRET|PASSWORD|KEY)/,
  'browser code must not read VITE_* secret-like values because Vite exposes them in the client bundle'
);

assert.doesNotMatch(
  `${appSource}\n${apiConfigSource}`,
  /X-Proxy-Sentinel-Token|searchParams\.set\(['"]token['"]/,
  'browser code must not attach privileged Proxy Sentinel API tokens to HTTP or WebSocket requests'
);
