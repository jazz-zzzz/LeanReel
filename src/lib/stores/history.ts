import { writable } from 'svelte/store';

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

export const history = writable<HistoryEntry[]>([]);
export const showHistory = writable<boolean>(false);
