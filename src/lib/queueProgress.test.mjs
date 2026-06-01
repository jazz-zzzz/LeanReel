import assert from 'node:assert/strict';
import test from 'node:test';

import { applyEncodeProgress, cancelActiveQueueItems, cancelQueueItem, hasActiveQueueItems } from './queueProgress.js';

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

test('marks every active queue item cancelled immediately after cancelling all tasks', () => {
  const runningTask = {
    ...pendingTask,
    id: 'encode-running.mkv',
    progress: 42,
    status: 'running',
    statusText: 'Transcode: 42%',
    stage: 'Transcode',
  };
  const finishedTask = {
    ...pendingTask,
    id: 'encode-finished.mkv',
    progress: 100,
    status: 'done',
    statusText: 'done',
  };

  const result = cancelActiveQueueItems([pendingTask, runningTask, finishedTask]);

  assert.equal(result[0].status, 'cancelled');
  assert.equal(result[0].progress, 100);
  assert.equal(result[1].status, 'cancelled');
  assert.equal(result[1].progress, 100);
  assert.equal(result[1].stage, undefined);
  assert.equal(result[2], finishedTask);
});

test('treats completed, cancelled, failed, and discarded tasks as terminal', () => {
  assert.equal(hasActiveQueueItems([
    { ...pendingTask, status: 'done' },
    { ...pendingTask, status: 'cancelled' },
    { ...pendingTask, status: 'failed' },
    { ...pendingTask, status: 'discarded' },
  ]), false);
  assert.equal(hasActiveQueueItems([pendingTask]), true);
});

test('does not revive a cancelled task when a late running event arrives', () => {
  const [cancelledTask] = cancelActiveQueueItems([pendingTask]);

  assert.deepEqual(
    applyEncodeProgress([cancelledTask], {
      job_id: pendingTask.id,
      stage: 'Transcode',
      progress: 73,
      status: 'running',
    }),
    [cancelledTask],
  );
});

test('marks only the selected queue item cancelled', () => {
  const otherTask = {
    ...pendingTask,
    id: 'encode-other.mkv',
  };

  const result = cancelQueueItem([pendingTask, otherTask], pendingTask.id);

  assert.equal(result[0].status, 'cancelled');
  assert.equal(result[0].progress, 100);
  assert.equal(result[1], otherTask);
});
