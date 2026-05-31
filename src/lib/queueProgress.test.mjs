import assert from 'node:assert/strict';
import test from 'node:test';

import { applyEncodeProgress } from './queueProgress.js';

const pendingTask = {
  id: 'encode-movie.mkv',
  fileName: 'movie.mkv',
  strategyName: 'HEVC',
  progress: 0,
  status: 'pending',
  statusText: '排队中',
};

test('updates a running task with a live transcode percentage', () => {
  assert.deepEqual(
    applyEncodeProgress([pendingTask], {
      job_id: 'encode-movie.mkv',
      stage: 'Transcode',
      progress: 37.54,
      status: 'running',
    }),
    [{
      ...pendingTask,
      progress: 37.5,
      status: 'running',
      statusText: 'Transcode: 37.5%',
      stage: 'Transcode',
    }],
  );
});

test('maps a completed backend event to the queue done status', () => {
  assert.deepEqual(
    applyEncodeProgress([pendingTask], {
      job_id: 'encode-movie.mkv',
      stage: 'done',
      progress: 100,
      status: 'completed',
    }),
    [{
      ...pendingTask,
      progress: 100,
      status: 'done',
      statusText: '已完成',
      stage: undefined,
    }],
  );
});
