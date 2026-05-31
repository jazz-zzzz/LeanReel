import assert from 'node:assert/strict';
import test from 'node:test';

import { addSelectionRange } from './selection.js';

const files = [
  { key: 'a', decision_status: 'processable' },
  { key: 'b', decision_status: 'protected' },
  { key: 'c', decision_status: 'processable' },
  { key: 'd', decision_status: 'processable' },
];

test('adds a forward range without clearing existing selection', () => {
  assert.deepEqual(
    addSelectionRange(files, ['existing'], 'a', 'd'),
    ['existing', 'a', 'c', 'd'],
  );
});

test('adds a reverse range in visible order', () => {
  assert.deepEqual(addSelectionRange(files, [], 'd', 'a'), ['a', 'c', 'd']);
});

test('skips files that are not processable', () => {
  assert.deepEqual(addSelectionRange(files, [], 'a', 'c'), ['a', 'c']);
});

test('toggles only the target when the anchor is not visible', () => {
  assert.deepEqual(addSelectionRange(files, ['a'], 'missing', 'c'), ['a', 'c']);
  assert.deepEqual(addSelectionRange(files, ['a', 'c'], 'missing', 'c'), ['a']);
});

test('does not select a protected target when the anchor is not visible', () => {
  assert.deepEqual(addSelectionRange(files, ['a'], 'missing', 'b'), ['a']);
});
