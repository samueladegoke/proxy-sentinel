import assert from 'node:assert/strict';

import { SoundNotifier } from '../src/lib/sound.js';

const notifier = new SoundNotifier();
notifier.setFrequency(1000);

const calls = [];
notifier.play = (frequency, duration) => {
  calls.push([frequency, duration]);
};

const originalSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (callback) => {
  callback();
  return 0;
};

try {
  notifier.playAlert();
} finally {
  globalThis.setTimeout = originalSetTimeout;
}

assert.deepEqual(
  calls,
  [
    [1000, 150],
    [1120, 150],
    [1330, 300]
  ],
  'alert tones should derive from the configured base frequency'
);

notifier.setFrequency('bad');
assert.equal(notifier.frequency, 1000, 'invalid frequency input should not erase the current frequency');

notifier.setFrequency(25000);
assert.equal(notifier.frequency, 20000, 'frequency should be clamped to a safe upper bound');
