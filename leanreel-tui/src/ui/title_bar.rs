use crate::app::Focus;
use crate::ui::theme;
use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::Line;
use ratatui::widgets::Paragraph;
use ratatui::Frame;

pub fn render(f: &mut Frame, area: Rect, focus: Focus) {
    let mode_text = match focus {
        Focus::Library => "Library",
        Focus::FileTable => "Files",
        Focus::StrategyPanel => "Strategy",
    };

    let title = format!(" LeanReel TUI  v0.1.0          Mode: {} ", mode_text);

    let p = Paragraph::new(Line::from(title))
        .style(Style::default().fg(theme::BG).bg(theme::ACCENT));
    f.render_widget(p, area);
}
