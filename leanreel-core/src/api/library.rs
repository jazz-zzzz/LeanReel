use crate::AppState;

pub fn create_library(name: &str, state: &AppState) -> Result<i64, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.create_library(name)
}

pub fn delete_library(id: i64, state: &AppState) -> Result<bool, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.delete_library(id)
}

pub fn list_libraries(
    state: &AppState,
) -> Result<Vec<crate::domain::models::LibraryInfo>, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.get_libraries()
}

pub fn add_folder(library_id: i64, path: &str, state: &AppState) -> Result<i64, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.add_folder(library_id, path)
}

pub fn remove_folder(
    library_id: i64,
    folder_id: i64,
    state: &AppState,
) -> Result<bool, String> {
    let _ = library_id;
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.remove_folder(folder_id)
}

pub fn get_folders(
    library_id: i64,
    state: &AppState,
) -> Result<Vec<crate::domain::models::FolderInfo>, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    store.get_folders(library_id)
}
