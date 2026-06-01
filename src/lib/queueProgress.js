/**
 * @typedef {'pending' | 'running' | 'done' | 'failed' | 'cancelled' | 'discarded'} QueueStatus
 * @typedef {{ id: string, fileName: string, strategyName: string, progress: number, status: QueueStatus, statusText: string, stage?: string }} QueueItem
 * @typedef {{ job_id: string, stage: string, progress: number, status: string }} EncodeProgress
 */

/**
 * @param {string} status
 * @returns {QueueStatus}
 */
function normalizeStatus(status) {
  if (status === 'completed') return 'done';
  if (status === 'discarded') return 'discarded';
  if (status === 'running' || status === 'failed' || status === 'cancelled') return status;
  return 'pending';
}

/**
 * @param {QueueStatus} status
 * @returns {string}
 */
function statusLabel(status) {
  if (status === 'done') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  if (status === 'discarded') return '输出未节省空间';
  if (status === 'running') return '运行中';
  return '排队中';
}

/**
 * @param {QueueStatus} status
 * @returns {boolean}
 */
export function isTerminalQueueStatus(status) {
  return status === 'done'
    || status === 'failed'
    || status === 'cancelled'
    || status === 'discarded';
}

/**
 * @param {QueueItem[]} items
 * @returns {boolean}
 */
export function hasActiveQueueItems(items) {
  return items.some((item) => !isTerminalQueueStatus(item.status));
}

/**
 * @param {QueueItem[]} items
 * @returns {QueueItem[]}
 */
export function cancelActiveQueueItems(items) {
  return items.map((item) => {
    if (isTerminalQueueStatus(item.status)) return item;
    return {
      ...item,
      progress: 100,
      status: 'cancelled',
      statusText: statusLabel('cancelled'),
      stage: undefined,
    };
  });
}

/**
 * @param {QueueItem[]} items
 * @param {string} jobId
 * @returns {QueueItem[]}
 */
export function cancelQueueItem(items, jobId) {
  return items.map((item) => {
    if (item.id !== jobId || isTerminalQueueStatus(item.status)) return item;
    return {
      ...item,
      progress: 100,
      status: 'cancelled',
      statusText: statusLabel('cancelled'),
      stage: undefined,
    };
  });
}

/**
 * Apply one backend progress event to the matching queue item.
 *
 * @param {QueueItem[]} items
 * @param {EncodeProgress} event
 * @returns {QueueItem[]}
 */
export function applyEncodeProgress(items, event) {
  return items.map((item) => {
    if (item.id !== event.job_id) return item;

    const progress = Math.round(event.progress * 10) / 10;
    const status = normalizeStatus(event.status);
    if (isTerminalQueueStatus(item.status) && !isTerminalQueueStatus(status)) return item;
    return {
      ...item,
      progress,
      status,
      statusText: event.stage === 'done' ? statusLabel(status) : `${event.stage}: ${progress}%`,
      stage: event.stage === 'done' ? undefined : event.stage,
    };
  });
}
