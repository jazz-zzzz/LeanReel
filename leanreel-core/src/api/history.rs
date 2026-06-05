use crate::domain::models::HistoryEntry;
use crate::AppState;

pub fn get_history(state: &AppState) -> Result<Vec<HistoryEntry>, String> {
    let store = state
        .store
        .lock()
        .map_err(|e| format!("锁获取失败: {}", e))?;
    store.get_compression_history_joined()
}
