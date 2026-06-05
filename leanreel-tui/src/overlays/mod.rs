pub mod history;
pub mod settings;
pub mod strategy_manager;

use leanreel_core::AppState;

pub struct OverlayCtx<'a> {
    pub state: &'a AppState,
    pub status_message: &'a mut String,
    pub needs_refresh_strategies: bool,
}
