import { writable } from 'svelte/store';

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

export const strategies = writable<StrategyItem[]>([]);
export const selectedStrategy = writable<StrategyItem | null>(null);
