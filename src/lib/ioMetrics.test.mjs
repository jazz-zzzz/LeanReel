import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeIoMetrics } from './ioMetrics.js';

test('normalizes process-level io metrics', () => {
  assert.deepEqual(
    normalizeIoMetrics(
      '{"io_type":"mixed","io_read_bytes_sec":100,"io_write_bytes_sec":50}',
    ),
    { type: '混合', readBytesSec: 100, writeBytesSec: 50 },
  );
});

test('falls back to old smb throughput fields', () => {
  assert.deepEqual(
    normalizeIoMetrics('{"smb_read_bytes_sec":100,"smb_write_bytes_sec":50}'),
    { type: 'SMB', readBytesSec: 100, writeBytesSec: 50 },
  );
});

test('returns null for records without io metrics', () => {
  assert.equal(normalizeIoMetrics('{"max_fps":120}'), null);
});

test('returns null for missing or malformed input', () => {
  assert.equal(normalizeIoMetrics(''), null);
  assert.equal(normalizeIoMetrics('not-json'), null);
});
