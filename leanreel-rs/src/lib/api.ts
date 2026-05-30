import { invoke } from '@tauri-apps/api/core';

export interface FileEntry {
    path: string;
    name: string;
    size: number;
    codec: string;
    hdr: string;
    size_display: string;
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
    description: string;
    savings: string;
    gpu: boolean;
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

export async function startEncode(
  files: string[],
  strategyName: string,
  workerCount?: number,
  deleteSource?: boolean,
): Promise<string> {
  return invoke('start_encode', {
    files,
    strategyName,
    workerCount: workerCount ?? 2,
    deleteSource: deleteSource ?? false,
  });
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
}

export async function getHistory(): Promise<HistoryEntry[]> {
  return invoke('get_history');
}
