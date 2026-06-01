import { invoke } from '@tauri-apps/api/core';

export interface FileEntry {
    key: string;
    folder_id: number;
    path: string;
    name: string;
    size: number;
    codec: string;
    hdr: string;
    size_display: string;
    width: number;
    height: number;
    bitrate_bps: number;
    decision_status: string;
    decision_text: string;
}

export interface ScanResult {
    total_files: number;
    probe_ok: number;
    probe_failed: number;
    files: FileEntry[];
}

export interface StrategyItem {
    name: string;
    encoder: string;
    cq: number;
    crf: number;
    description: string;
    savings: string;
    gpu: boolean;
    preset: string;
    sort_order: number;
    is_preset: boolean;
}

export interface StrategyListResult {
    count: number;
    message: string;
    strategies: StrategyItem[];
}

export async function getLibraryFiles(libraryId: number): Promise<ScanResult> {
  return invoke('get_library_files', { libraryId });
}

export async function getFolderFiles(folderId: number): Promise<ScanResult> {
  return invoke('get_folder_files', { folderId });
}

export async function scanDirectory(path: string, folderId: number): Promise<ScanResult> {
  return invoke('scan_directory', { path, folderId });
}

export interface LibraryInfo {
  id: number;
  name: string;
  created_at: string;
  folders: FolderInfo[];
}

export interface FolderInfo {
  id: number;
  path: string;
}

export async function createLibrary(name: string): Promise<number> {
  return invoke('create_library', { name });
}

export async function deleteLibrary(id: number): Promise<boolean> {
  return invoke('delete_library', { id });
}

export async function listLibraries(): Promise<LibraryInfo[]> {
  return invoke('list_libraries');
}

export async function addFolder(libraryId: number, path: string): Promise<number> {
  return invoke('add_folder', { libraryId, path });
}

export async function removeFolder(libraryId: number, folderId: number): Promise<boolean> {
  return invoke('remove_folder', { libraryId, folderId });
}

export async function getFolders(libraryId: number): Promise<FolderInfo[]> {
  return invoke('get_folders', { libraryId });
}

export async function loadStrategies(): Promise<StrategyListResult> {
  return invoke('load_strategies');
}

export async function saveStrategy(name: string, json: string): Promise<void> {
  return invoke('save_strategy', { name, strategyJson: json });
}

interface SortOrderEntry { name: string; sort_order: number; }
export async function saveStrategyOrder(order: SortOrderEntry[]): Promise<void> {
  return invoke('save_strategy_order', { order });
}

export async function deleteStrategy(name: string): Promise<void> {
  return invoke('delete_strategy', { name });
}

export async function startEncode(
  files: string[],
  strategyName: string,
  deleteSource?: boolean,
  workerCount?: number,
  customStrategy?: CustomStrategy,
): Promise<StartEncodeResult> {
  return invoke('start_encode', {
    files,
    strategyName,
    deleteSource: deleteSource ?? false,
    workerCount: workerCount ?? 2,
    customStrategy,
  });
}

export interface CustomStrategy {
  encoder: string;
  cq: number;
  crf: number;
  preset: string;
  audio: string;
  sub: string;
}

export interface SubmittedQueueItem {
  id: string;
  file_key: string;
  file_name: string;
  strategy_name: string;
}

export interface StartEncodeResult {
  message: string;
  jobs: SubmittedQueueItem[];
}

export async function getQueueStatus(): Promise<{ paused: boolean; cancelled: boolean }> {
  return invoke('get_queue_status');
}

export async function pauseEncode(): Promise<void> {
  return invoke('pause_encode');
}

export async function resumeEncode(): Promise<void> {
  return invoke('resume_encode');
}

export async function cancelEncode(): Promise<void> {
  return invoke('cancel_encode');
}

export async function cancelTask(jobId: string): Promise<void> {
  return invoke('cancel_task', { jobId });
}

export interface HistoryEntry {
    id: number;
    source_path: string;
    output_path: string;
    source_size_bytes: number;
    output_size_bytes: number;
    savings_pct: number;
    strategy_name: string;
    encoder: string;
    status: string;
    duration_ms: number;
    completed_at: string;
    success: boolean;
    // ── Expanded fields (M8 fix) ──────────────────────────────────────
    cq_value: number;
    preset: string;
    pix_fmt: string;
    audio_mode: string;
    sub_mode: string;
    ffmpeg_command: string;
    leanreel_version: string;
    batch_id: string;
    stage: string;
    started_at: string;
    source_deleted: boolean;
    error_message: string;
    performance_metrics: string;
}

export async function getHistory(): Promise<HistoryEntry[]> {
  return invoke('get_history');
}

export interface AppSettings {
  ffprobe_custom: string;
  ffmpeg_custom: string;
  ffprobe_path: string;
  ffmpeg_path: string;
  ffprobe_ok: boolean;
  ffmpeg_ok: boolean;
  gpu_ok: boolean;
  gpu_info: string;
}

export async function getSettings(): Promise<AppSettings> {
  return invoke('get_settings');
}

export async function testTool(path: string): Promise<boolean> {
  return invoke('test_tool', { path });
}

export async function saveSettings(ffprobe_path?: string, ffmpeg_path?: string): Promise<AppSettings> {
  return invoke('save_settings', { ffprobePath: ffprobe_path, ffmpegPath: ffmpeg_path });
}
