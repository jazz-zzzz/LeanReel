import { writable } from 'svelte/store';

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

export const files = writable<FileEntry[]>([]);
export const scanStatus = writable<string>('');
export const selectedFilePaths = writable<string[]>([]);

export type ScanPhase = 'discovering' | 'probing' | 'done';

export interface ScanPhaseEvent {
  scan_id: string;
  folder_id: number;
  phase: ScanPhase;
}

export interface ScanProgressState {
  scan_id: string;
  folder_id: number;
  phase: ScanPhase;
  done: number;
  total: number;
  visited_entries?: number;
  video_files_found?: number;
}

export const scanProgress = writable<ScanProgressState | null>(null);
