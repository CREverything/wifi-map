import test from 'node:test';
import assert from 'node:assert/strict';
import { validateModelResponse, EXAMPLE_RESPONSE } from './model-response.js';

test('accepts valid and empty model results', () => {
  assert.deepEqual(validateModelResponse(EXAMPLE_RESPONSE), EXAMPLE_RESPONSE);
  assert.deepEqual(validateModelResponse({ version: 1, summary: 'No areas', areas: [] }).areas, []);
});

test('rejects invalid model fields', () => {
  for (const change of [{ latitude: 91 }, { intensity: 2 }, { radius_m: -1 }, { longitude: '0' }, { explanation: null }]) {
    assert.throws(() => validateModelResponse({ ...EXAMPLE_RESPONSE, areas: [{ ...EXAMPLE_RESPONSE.areas[0], ...change }] }));
  }
});

test('rejects prose and unsupported versions', () => {
  for (const value of ['Here is your map', null, { ...EXAMPLE_RESPONSE, version: 2 }]) {
    assert.throws(() => validateModelResponse(value));
  }
});
