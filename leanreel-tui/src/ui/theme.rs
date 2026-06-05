use ratatui::style::{Color, Modifier, Style};

pub const BG: Color = Color::Rgb(18, 18, 18);
pub const FG: Color = Color::Rgb(220, 220, 220);
pub const ACCENT: Color = Color::Rgb(59, 130, 246);
pub const DIM: Color = Color::Rgb(100, 100, 100);
pub const BORDER: Color = Color::Rgb(60, 60, 60);
pub const GREEN: Color = Color::Rgb(34, 197, 94);
pub const RED: Color = Color::Rgb(239, 68, 68);
pub const YELLOW: Color = Color::Rgb(234, 179, 8);
pub const BLUE: Color = Color::Rgb(59, 130, 246);

pub fn accent() -> Style {
    Style::default().fg(ACCENT)
}

pub fn dim() -> Style {
    Style::default().fg(DIM)
}

pub fn green() -> Style {
    Style::default().fg(GREEN)
}

pub fn red() -> Style {
    Style::default().fg(RED)
}

pub fn yellow() -> Style {
    Style::default().fg(YELLOW)
}

pub fn bold() -> Style {
    Style::default().add_modifier(Modifier::BOLD)
}

pub fn selected() -> Style {
    Style::default().bg(Color::Rgb(55, 65, 81)).fg(Color::White)
}

pub fn border_style() -> Style {
    Style::default().fg(BORDER)
}
