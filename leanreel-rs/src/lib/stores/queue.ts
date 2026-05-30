import { writable } from 'svelte/store';

export type QueueStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled';

export interface QueueItem {
    id: string;
    fileName: string;
    strategyName: string;
    progress: number;
    status: QueueStatus;
    statusText: string;
    stage?: string;
}

export const queue = writable<QueueItem[]>([]);
