use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::domain::models::{FolderInfo, LibraryInfo};
use leanreel_core::AppState;
use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState};
use ratatui::Frame;

pub enum LibraryAction {
    None,
    RefreshLibraries,
    RefreshFiles(i64),
    SetStatus(String),
    LoadFolders(i64),
}

pub struct LibraryPanelState {
    pub libraries: Vec<LibraryInfo>,
    pub folders: Vec<FolderInfo>,
    pub expanded_libs: std::collections::HashSet<i64>,
    pub selected_library_id: Option<i64>,
    pub selected_folder_id: Option<i64>,
    pub list_state: ListState,
}

impl LibraryPanelState {
    pub fn new() -> Self {
        let mut state = Self {
            libraries: Vec::new(),
            folders: Vec::new(),
            expanded_libs: std::collections::HashSet::new(),
            selected_library_id: None,
            selected_folder_id: None,
            list_state: ListState::default(),
        };
        state.list_state.select(Some(0));
        state
    }

    pub fn load_folders(&mut self, state: &AppState, library_id: i64) {
        if let Ok(folders) = leanreel_core::api::library::get_folders(library_id, state) {
            self.folders.retain(|f| f.library_id != library_id);
            self.folders.extend(folders);
        }
    }

    fn flat_index(&self) -> usize {
        self.list_state.selected().unwrap_or(0)
    }

    pub fn handle_key(&mut self, key: KeyEvent, state: &AppState) -> LibraryAction {
        match key.code {
            KeyCode::Up => {
                let total_items = self.total_items();
                if total_items > 0 {
                    let idx = self.flat_index();
                    let new = if idx == 0 { total_items - 1 } else { idx - 1 };
                    self.list_state.select(Some(new));
                }
                LibraryAction::None
            }
            KeyCode::Down => {
                let total_items = self.total_items();
                if total_items > 0 {
                    let idx = self.flat_index();
                    let new = if idx + 1 >= total_items { 0 } else { idx + 1 };
                    self.list_state.select(Some(new));
                }
                LibraryAction::None
            }
            KeyCode::Enter => {
                let total = self.total_items();
                let idx = self.flat_index();
                if idx >= total {
                    return LibraryAction::None;
                }

                let mut flat_idx = 0;
                for lib in &self.libraries.clone() {
                    if flat_idx == idx {
                        if self.expanded_libs.contains(&lib.id) {
                            self.expanded_libs.remove(&lib.id);
                        } else {
                            self.expanded_libs.insert(lib.id);
                            return LibraryAction::LoadFolders(lib.id);
                        }
                        self.selected_library_id = Some(lib.id);
                        self.selected_folder_id = None;
                        return LibraryAction::None;
                    }
                    flat_idx += 1;

                    if self.expanded_libs.contains(&lib.id) {
                        for folder in &self.folders {
                            if folder.library_id == lib.id {
                                if flat_idx == idx {
                                    self.selected_folder_id = Some(folder.id);
                                    self.selected_library_id = Some(lib.id);
                                    return LibraryAction::RefreshFiles(folder.id);
                                }
                                flat_idx += 1;
                            }
                        }
                    }
                }
                LibraryAction::None
            }
            KeyCode::Char('n') => {
                let name = format!("库 {}", self.libraries.len() + 1);
                if let Ok(id) = leanreel_core::api::library::create_library(&name, state) {
                    self.expanded_libs.insert(id);
                    LibraryAction::SetStatus(format!("已创建: {}", name))
                } else {
                    LibraryAction::SetStatus("创建库失败".into())
                }
            }
            KeyCode::Char('d') => {
                if let Some(id) = self.selected_library_id {
                    let _ = leanreel_core::api::library::delete_library(id, state);
                    self.selected_library_id = None;
                    LibraryAction::SetStatus("已删除库".into())
                } else {
                    LibraryAction::None
                }
            }
            _ => LibraryAction::None,
        }
    }

    fn total_items(&self) -> usize {
        let mut count = 0;
        for lib in &self.libraries {
            count += 1;
            if self.expanded_libs.contains(&lib.id) {
                count += self.folders.iter().filter(|f| f.library_id == lib.id).count();
            }
        }
        count
    }

    pub fn selected_folder_id(&self) -> i64 {
        self.selected_folder_id.unwrap_or(0)
    }

    pub fn selected_folder_path(&self) -> String {
        if let Some(fid) = self.selected_folder_id {
            for f in &self.folders {
                if f.id == fid {
                    return f.path.clone();
                }
            }
        }
        String::new()
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &mut LibraryPanelState, is_focused: bool) {
    let border_style = if is_focused {
        Style::default().fg(theme::ACCENT)
    } else {
        theme::border_style()
    };

    let mut items: Vec<ListItem> = Vec::new();

    for lib in &state.libraries {
        let expanded = state.expanded_libs.contains(&lib.id);
        let arrow = if expanded { "▾" } else { "▸" };
        let is_selected_lib = state.selected_library_id == Some(lib.id);
        let folder_count = state
            .folders
            .iter()
            .filter(|f| f.library_id == lib.id)
            .count();
        let style = if is_selected_lib {
            theme::accent()
        } else {
            theme::dim()
        };
        items.push(ListItem::new(Line::from(Span::styled(
            format!("{} {}  [{} 个文件夹]", arrow, lib.name, folder_count),
            style,
        ))));

        if expanded {
            for folder in &state.folders {
                if folder.library_id == lib.id {
                    let is_sel = state.selected_folder_id == Some(folder.id);
                    let fstyle = if is_sel {
                        theme::accent()
                    } else {
                        theme::dim()
                    };
                    items.push(ListItem::new(Line::from(Span::styled(
                        format!("    /{}", folder.path),
                        fstyle,
                    ))));
                }
            }
            items.push(ListItem::new(Line::from(Span::styled(
                "    [+ 添加文件夹]",
                theme::dim(),
            ))));
        }
    }

    items.push(ListItem::new(Line::from(Span::styled(
        "[n] 新建库  [d] 删除选中",
        theme::dim(),
    ))));

    let list = List::new(items)
        .block(
            Block::default()
                .title(" 库 ")
                .borders(Borders::ALL)
                .border_style(border_style),
        )
        .highlight_style(theme::selected());

    f.render_stateful_widget(list, area, &mut state.list_state);
}
