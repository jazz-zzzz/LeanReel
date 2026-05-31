use crate::domain::models::Strategy;
use crate::AppState;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use tauri::State;

/// Load strategies from disk, searching in order:
/// 1. <exe_dir>/strategies/
/// 2. strategies/
/// 3. ../strategies/
///
/// Deduplicates by name (first occurrence wins). Sorted by sort_order.
pub fn load_strategies_from_disk() -> Result<Vec<Strategy>, String> {
    let mut strategies = Vec::new();
    let mut seen_names: HashSet<String> = HashSet::new();
    let dirs = [
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.join("strategies"))),
        Some(std::path::PathBuf::from("strategies")),
        Some(std::path::PathBuf::from("../strategies")),
    ]
    .into_iter()
    .flatten();
    let mut found = None;
    for d in dirs {
        if d.exists() && d.is_dir() {
            found = Some(d);
            break;
        }
    }
    let dir = found.ok_or("未找到策略目录".to_string())?;
    for entry in fs::read_dir(&dir).map_err(|e| format!("读取失败: {}", e))? {
        let entry = entry.map_err(|_| "读取文件失败".to_string())?;
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("json") {
            let json = fs::read_to_string(&path).map_err(|e| e.to_string())?;
            let s: Strategy = serde_json::from_str(&json).map_err(|e| e.to_string())?;
            if seen_names.contains(&s.name) {
                continue;
            }
            seen_names.insert(s.name.clone());
            strategies.push(s);
        }
    }
    strategies.sort_by_key(|s| s.sort_order);
    Ok(strategies)
}

fn resolve_strategy_dir() -> Result<std::path::PathBuf, String> {
    let dirs = [
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.join("strategies"))),
        Some(std::path::PathBuf::from("strategies")),
        Some(std::path::PathBuf::from("../strategies")),
    ]
    .into_iter()
    .flatten();
    for d in dirs {
        if d.exists() && d.is_dir() {
            return Ok(d);
        }
    }
    Err("未找到策略目录".to_string())
}

#[derive(Debug, Clone, Serialize)]
pub struct StrategyItem {
    pub name: String,
    pub encoder: String,
    pub cq: i32,
    pub crf: i32,
    pub description: String,
    pub savings: String,
    pub gpu: bool,
    pub preset: String,
    pub sort_order: i32,
    pub is_preset: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct StrategyListResult {
    pub count: usize,
    pub message: String,
    pub strategies: Vec<StrategyItem>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SortOrderEntry {
    pub name: String,
    pub sort_order: i32,
}

#[tauri::command]
pub fn load_strategies(state: State<AppState>) -> Result<StrategyListResult, String> {
    let strategies = load_strategies_from_disk()?;
    let count = strategies.len();

    let items: Vec<StrategyItem> = strategies
        .iter()
        .map(|s| StrategyItem {
            name: s.name.clone(),
            encoder: s.video.encoder.clone(),
            cq: s.video.cq,
            crf: s.video.crf,
            description: s.description.clone(),
            savings: s.estimated_savings.clone(),
            gpu: s.video.gpu,
            preset: s.video.preset.clone(),
            sort_order: s.sort_order,
            is_preset: s.is_preset,
        })
        .collect();

    let mut matcher = state
        .matcher
        .lock()
        .map_err(|_| "策略锁获取失败".to_string())?;
    *matcher = crate::services::matcher::StrategyMatcher::new(strategies);

    Ok(StrategyListResult {
        count,
        message: format!("已加载 {} 个策略", count),
        strategies: items,
    })
}

#[tauri::command]
pub fn save_strategy(
    name: String,
    strategy_json: String,
    state: State<AppState>,
) -> Result<(), String> {
    let dir = resolve_strategy_dir()?;
    let path = dir.join(format!("{}.json", name));
    fs::write(&path, strategy_json).map_err(|e| format!("写入策略失败: {}", e))?;
    let strategies = load_strategies_from_disk()?;
    if let Ok(mut matcher) = state.matcher.lock() {
        *matcher = crate::services::matcher::StrategyMatcher::new(strategies);
    }
    Ok(())
}

#[tauri::command]
pub fn delete_strategy(name: String, state: State<AppState>) -> Result<(), String> {
    let dir = resolve_strategy_dir()?;
    let path = dir.join(format!("{}.json", name));
    if path.exists() {
        fs::remove_file(&path).map_err(|e| format!("删除策略失败: {}", e))?;
    }
    let strategies = load_strategies_from_disk()?;
    if let Ok(mut matcher) = state.matcher.lock() {
        *matcher = crate::services::matcher::StrategyMatcher::new(strategies);
    }
    Ok(())
}

#[tauri::command]
pub fn save_strategy_order(
    order: Vec<SortOrderEntry>,
    state: State<AppState>,
) -> Result<(), String> {
    let dir = resolve_strategy_dir()?;
    for entry in &order {
        let path = dir.join(format!("{}.json", entry.name));
        if let Ok(json) = fs::read_to_string(&path) {
            if let Ok(mut strategy) = serde_json::from_str::<Strategy>(&json) {
                strategy.sort_order = entry.sort_order;
                let new_json =
                    serde_json::to_string_pretty(&strategy).map_err(|e| e.to_string())?;
                fs::write(&path, new_json).map_err(|e| e.to_string())?;
            }
        }
    }
    // Reload matcher with updated order
    let strategies = load_strategies_from_disk()?;
    if let Ok(mut matcher) = state.matcher.lock() {
        *matcher = crate::services::matcher::StrategyMatcher::new(strategies);
    }
    Ok(())
}
