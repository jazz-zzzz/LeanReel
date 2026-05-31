use crate::AppState;
use tauri::State;

#[tauri::command]
pub fn create_library(name: String, state: State<AppState>) -> Result<i64, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.create_library(&name)
}

#[tauri::command]
pub fn delete_library(id: i64, state: State<AppState>) -> Result<bool, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.delete_library(id)
}

#[tauri::command]
pub fn list_libraries(
    state: State<AppState>,
) -> Result<Vec<crate::domain::models::LibraryInfo>, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.get_libraries()
}

#[tauri::command]
pub fn add_folder(library_id: i64, path: String, state: State<AppState>) -> Result<i64, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.add_folder(library_id, &path)
}

#[tauri::command]
pub fn remove_folder(
    library_id: i64,
    folder_id: i64,
    state: State<AppState>,
) -> Result<bool, String> {
    // library_id is received but unused — the DB cascade deletes by folder_id alone.
    // It is kept in the signature to match the frontend API contract.
    let _ = library_id;
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.remove_folder(folder_id)
}

#[tauri::command]
pub fn get_folders(
    library_id: i64,
    state: State<AppState>,
) -> Result<Vec<crate::domain::models::FolderInfo>, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.get_folders(library_id)
}
