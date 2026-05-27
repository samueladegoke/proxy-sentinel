import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const frontendRoot = fileURLToPath(new URL('..', import.meta.url));

function textOf(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  return textOf(node.props?.children);
}

function findElements(node, predicate, results = []) {
  if (node === null || node === undefined || typeof node !== 'object') return results;
  if (predicate(node)) results.push(node);

  const children = node.props?.children;
  const childList = Array.isArray(children) ? children : [children];
  for (const child of childList) {
    findElements(child, predicate, results);
  }
  return results;
}

const server = await createServer({
  root: frontendRoot,
  appType: 'custom',
  logLevel: 'silent',
  server: { middlewareMode: true }
});

try {
  const { ProgressBar } = await server.ssrLoadModule('/src/components/ProgressBar.jsx');
  const missingDuration = renderToStaticMarkup(
    React.createElement(ProgressBar, { completed: 0, total: 10 })
  );
  assert.match(missingDuration, /Checking 0\/10/);
  assert.match(missingDuration, /0\.0s elapsed/);

  const overComplete = renderToStaticMarkup(
    React.createElement(ProgressBar, { completed: 15, total: 10, duration: '1' })
  );
  assert.match(overComplete, />100%<\/span>/);
  assert.match(overComplete, /width:100%/);
  assert.match(overComplete, /15\.0 proxies\/sec/);

  const { StatCard } = await server.ssrLoadModule('/src/components/StatCard.jsx');
  const statCard = renderToStaticMarkup(
    React.createElement(StatCard, {
      title: 'Total proxies',
      value: null,
      tone: 'unknown',
      helper: 'Fallback helper',
      icon: React.createElement('span', null, 'Icon')
    })
  );
  assert.match(statCard, /Total proxies/);
  assert.match(statCard, />0<\/div>/);
  assert.match(statCard, /Fallback helper/);
  assert.match(statCard, /Icon/);

  const { Toast } = await server.ssrLoadModule('/src/components/Toast.jsx');
  const toast = renderToStaticMarkup(
    React.createElement(Toast, { message: 'Saved', type: 'success', onClose: () => {} })
  );
  assert.match(toast, /Saved/);
  assert.match(toast, /aria-label="Close notification"/);

  const soundModule = await server.ssrLoadModule('/src/lib/sound.js');
  const { SettingsPanel } = await server.ssrLoadModule('/src/components/SettingsPanel.jsx');
  const settings = {
    soundEnabled: true,
    volume: 0.4,
    frequency: 1200,
    toastEnabled: true,
    trackingInterval: 5
  };
  const enabledCalls = [];
  const originalSetEnabled = soundModule.soundNotifier.setEnabled;
  const originalSetVolume = soundModule.soundNotifier.setVolume;
  const originalSetFrequency = soundModule.soundNotifier.setFrequency;
  const originalPlayAlert = soundModule.soundNotifier.playAlert;
  soundModule.soundNotifier.setEnabled = (value) => enabledCalls.push(value);
  soundModule.soundNotifier.setVolume = (value) => enabledCalls.push(['volume', value]);
  soundModule.soundNotifier.setFrequency = (value) => enabledCalls.push(['frequency', value]);
  soundModule.soundNotifier.playAlert = () => enabledCalls.push('play');

  try {
    let changedSettings = null;
    const panel = SettingsPanel({
      settings,
      onSettingsChange: (next) => {
        changedSettings = next;
      },
      onClose: () => {}
    });
    const buttons = findElements(panel, (node) => node.type === 'button');
    const soundToggle = buttons[1];
    soundToggle.props.onClick();
    assert.equal(changedSettings.soundEnabled, false);
    assert.deepEqual(enabledCalls.shift(), false);

    const testButton = buttons.find((button) => textOf(button) === 'Test Sound');
    testButton.props.onClick();
    assert.deepEqual(enabledCalls, [true, ['volume', 0.4], ['frequency', 1200], 'play']);

    const disabledPanel = SettingsPanel({
      settings: { ...settings, soundEnabled: false },
      onSettingsChange: () => {},
      onClose: () => {}
    });
    const disabledTestButton = findElements(disabledPanel, (node) => node.type === 'button')
      .find((button) => textOf(button) === 'Test Sound');
    assert.equal(disabledTestButton.props.disabled, true);
  } finally {
    soundModule.soundNotifier.setEnabled = originalSetEnabled;
    soundModule.soundNotifier.setVolume = originalSetVolume;
    soundModule.soundNotifier.setFrequency = originalSetFrequency;
    soundModule.soundNotifier.playAlert = originalPlayAlert;
  }
} finally {
  await server.close();
}
