import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createInitialScanUiState,
  beginScan,
  applyScanPhase,
  applyScanProgress,
  formatAddFolderStatus,
  formatLibraryScanStatus,
  scanErrorMessage,
} from './scanProgress.js';

test('beginScan creates immediate visible discovery state', () => {
  const state = beginScan(createInitialScanUiState(), {
    scanId: 'scan-1',
    folderId: 12,
    label: 'Movies',
  });

  assert.equal(state.activeScanId, 'scan-1');
  assert.equal(state.folderId, 12);
  assert.equal(state.phase, 'discovering');
  assert.equal(state.progressMode, 'indeterminate');
  assert.equal(state.visible, true);
  assert.equal(state.statusText, '正在扫描目录 Movies...');
});

test('discovery progress formats visited and found counts', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-1',
    folderId: 12,
    label: 'Movies',
  });
  const state = applyScanProgress(started, {
    scan_id: 'scan-1',
    folder_id: 12,
    phase: 'discovering',
    done: 23,
    total: 0,
    visited_entries: 1234,
    video_files_found: 23,
  });

  assert.equal(state.progressMode, 'indeterminate');
  assert.equal(state.statusText, '正在扫描目录 Movies...已访问 1,234 项，发现 23 个视频');
  assert.equal(state.progress.done, 23);
  assert.equal(state.progress.total, 0);
});

test('probing phase and progress switch to determinate mode', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-2',
    folderId: 3,
    label: 'Anime',
  });
  const probing = applyScanPhase(started, {
    scan_id: 'scan-2',
    folder_id: 3,
    phase: 'probing',
  });
  const state = applyScanProgress(probing, {
    scan_id: 'scan-2',
    folder_id: 3,
    phase: 'probing',
    done: 45,
    total: 150,
  });

  assert.equal(state.progressMode, 'determinate');
  assert.equal(state.statusText, '正在分析文件 45/150');
  assert.equal(state.progress.done, 45);
  assert.equal(state.progress.total, 150);
});

test('ignores stale scan events', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'new-scan',
    folderId: 1,
    label: 'New',
  });
  const state = applyScanProgress(started, {
    scan_id: 'old-scan',
    folder_id: 1,
    phase: 'discovering',
    done: 99,
    total: 0,
    visited_entries: 999,
    video_files_found: 99,
  });

  assert.deepEqual(state, started);
});

test('done phase keeps a complete visible state for delayed hiding', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-3',
    folderId: 5,
    label: 'Done',
  });
  const state = applyScanPhase(started, {
    scan_id: 'scan-3',
    folder_id: 5,
    phase: 'done',
  });

  assert.equal(state.phase, 'done');
  assert.equal(state.progressMode, 'determinate');
  assert.equal(state.visible, true);
  assert.equal(state.statusText, '扫描完成');
});

test('library scan status reports folder failures instead of masking them', () => {
  assert.equal(
    formatLibraryScanStatus({ totalFiles: 8, totalOk: 6, failedCount: 2 }),
    '扫描结束: 8 文件, 6 成功，2 个文件夹失败',
  );
});

test('library scan status reports clean success when every folder scans', () => {
  assert.equal(
    formatLibraryScanStatus({ totalFiles: 8, totalOk: 8 }),
    '扫描完成: 8 文件, 8 成功',
  );
});

test('add folder status preserves initial scan failure', () => {
  assert.equal(
    formatAddFolderStatus('D:\\Media', { ok: false, error: 'ffprobe not found' }),
    '已添加 D:\\Media，但初次扫描失败: ffprobe not found',
  );
});

test('add folder status reports plain success when refresh succeeds', () => {
  assert.equal(
    formatAddFolderStatus('D:\\Media', { ok: true, result: {} }),
    '已添加 D:\\Media',
  );
});

test('scanErrorMessage normalizes thrown values', () => {
  assert.equal(scanErrorMessage(new Error('missing tool')), 'missing tool');
  assert.equal(scanErrorMessage('plain failure'), 'plain failure');
});
