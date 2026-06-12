/**
 * @typedef {'discovering' | 'probing' | 'done'} ScanPhase
 * @typedef {'hidden' | 'indeterminate' | 'determinate'} ProgressMode
 * @typedef {{ scan_id: string, folder_id: number, phase: ScanPhase, done: number, total: number, visited_entries?: number, video_files_found?: number }} ScanProgressEvent
 * @typedef {{ scan_id: string, folder_id: number, phase: ScanPhase }} ScanPhaseEvent
 * @typedef {{ activeScanId: string | null, folderId: number | null, label: string, phase: ScanPhase | null, progressMode: ProgressMode, visible: boolean, statusText: string, progress: ScanProgressEvent | null }} ScanUiState
 */

/**
 * @returns {ScanUiState}
 */
export function createInitialScanUiState() {
  return {
    activeScanId: null,
    folderId: null,
    label: '',
    phase: null,
    progressMode: 'hidden',
    visible: false,
    statusText: '',
    progress: null,
  };
}

/**
 * @param {ScanUiState} _state
 * @param {{ scanId: string, folderId: number, label?: string }} scan
 * @returns {ScanUiState}
 */
export function beginScan(_state, { scanId, folderId, label }) {
  const safeLabel = label || '';
  return {
    activeScanId: scanId,
    folderId,
    label: safeLabel,
    phase: 'discovering',
    progressMode: 'indeterminate',
    visible: true,
    statusText: `正在扫描目录${safeLabel ? ` ${safeLabel}` : ''}...`,
    progress: {
      scan_id: scanId,
      folder_id: folderId,
      phase: 'discovering',
      done: 0,
      total: 0,
      visited_entries: 0,
      video_files_found: 0,
    },
  };
}

/**
 * @param {ScanUiState} state
 * @param {ScanPhaseEvent | ScanProgressEvent} event
 * @returns {boolean}
 */
function isCurrentScan(state, event) {
  return state.activeScanId === event.scan_id;
}

/**
 * @param {ScanUiState} state
 * @param {ScanPhaseEvent} event
 * @returns {ScanUiState}
 */
export function applyScanPhase(state, event) {
  if (!isCurrentScan(state, event)) return state;
  if (event.phase === 'probing') {
    return {
      ...state,
      phase: 'probing',
      progressMode: 'determinate',
      visible: true,
      statusText: '正在分析文件 0/0',
      progress: {
        scan_id: event.scan_id,
        folder_id: event.folder_id,
        phase: 'probing',
        done: 0,
        total: 0,
      },
    };
  }
  if (event.phase === 'done') {
    return {
      ...state,
      phase: 'done',
      progressMode: 'determinate',
      visible: true,
      statusText: '扫描完成',
      progress: {
        scan_id: event.scan_id,
        folder_id: event.folder_id,
        phase: 'done',
        done: 1,
        total: 1,
      },
    };
  }
  return {
    ...state,
    phase: 'discovering',
    progressMode: 'indeterminate',
    visible: true,
  };
}

/**
 * @param {ScanUiState} state
 * @param {ScanProgressEvent} event
 * @returns {ScanUiState}
 */
export function applyScanProgress(state, event) {
  if (!isCurrentScan(state, event)) return state;
  if (event.phase === 'discovering') {
    const visited = event.visited_entries ?? 0;
    const found = event.video_files_found ?? event.done ?? 0;
    return {
      ...state,
      phase: 'discovering',
      progressMode: 'indeterminate',
      visible: true,
      statusText: `正在扫描目录${state.label ? ` ${state.label}` : ''}...已访问 ${visited.toLocaleString()} 项，发现 ${found.toLocaleString()} 个视频`,
      progress: event,
    };
  }

  const total = event.total || 0;
  const done = event.done || 0;
  return {
    ...state,
    phase: 'probing',
    progressMode: 'determinate',
    visible: true,
    statusText: `正在分析文件 ${done}/${total}`,
    progress: event,
  };
}

/**
 * @param {{ totalFiles: number, totalOk: number, failedCount?: number }} summary
 * @returns {string}
 */
export function formatLibraryScanStatus({ totalFiles, totalOk, failedCount = 0 }) {
  if (failedCount > 0) {
    return `扫描结束: ${totalFiles} 文件, ${totalOk} 成功，${failedCount} 个文件夹失败`;
  }
  return `扫描完成: ${totalFiles} 文件, ${totalOk} 成功`;
}

/**
 * @param {string} path
 * @param {{ ok: boolean, error?: string }} refreshResult
 * @returns {string}
 */
export function formatAddFolderStatus(path, refreshResult) {
  if (!refreshResult.ok) {
    return `已添加 ${path}，但初次扫描失败: ${refreshResult.error || '未知错误'}`;
  }
  return `已添加 ${path}`;
}

/**
 * @param {unknown} error
 * @returns {string}
 */
export function scanErrorMessage(error) {
  if (error instanceof Error) return error.message;
  return String(error);
}
