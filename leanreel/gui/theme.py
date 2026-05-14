"""LeanReel 暗色主题 — OKLCH 色彩系统，类似 TMM 风格"""
from PySide6.QtWidgets import QApplication

# ── 色彩标记 ──
C_BASE = "#12100e"        # 基色 ~12%L，暖色底
C_SURFACE = "#1c1a16"     # 面版 ~17%L
C_SURFACE_RAISED = "#24221d"  # 悬浮面 ~21%L
C_BORDER = "#2e2b25"      # 边框 ~25%L
C_BORDER_FOCUS = "#5c4a2e"   # 聚焦边框 琥珀色
C_TEXT = "#e8e3db"        # 主文字 ~92%L
C_TEXT_SECONDARY = "#8a857c"  # 次文字 ~58%L
C_TEXT_MUTED = "#5c5851"  # 弱文字 ~40%L
C_ACCENT = "#c8963e"      # 琥珀强调 ~65L 0.14C
C_ACCENT_HOVER = "#d9a84c"   # 悬停琥珀
C_GREEN = "#6b9955"       # 成功绿
C_RED = "#c4554a"         # 失败红
C_YELLOW = "#c8a23e"      # 警告黄
C_BLUE = "#5b8db8"        # 信息蓝
C_GRAY = "#5c5851"        # 灰色
C_ROW_ALT = "#171512"     # 交替行色
C_SELECTION = "#2a2215"   # 选中行色
C_PROGRESS_BG = "#24221d"
C_PROGRESS_CHUNK = "#c8963e"

# ── 字体 ──
FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", sans-serif'
FONT_SIZE = "13px"
FONT_MONO = '"Cascadia Code", "Consolas", "Fira Code", monospace'

QSS = f"""
/* ── 全局 ── */
* {{
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE};
    color: {C_TEXT};
}}

QMainWindow {{
    background-color: {C_BASE};
}}

QMainWindow::separator {{
    width: 1px;
    background: {C_BORDER};
}}

/* ── 分割器 ── */
QSplitter::handle {{
    background: {C_BORDER};
    margin: 0 1px;
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── 树形控件 ── */
QTreeWidget {{
    background-color: {C_SURFACE};
    alternate-background-color: {C_ROW_ALT};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    outline: none;
    padding: 2px;
}}
QTreeWidget::item {{
    padding: 4px 6px;
    border-radius: 3px;
}}
QTreeWidget::item:hover {{
    background-color: {C_SURFACE_RAISED};
}}
QTreeWidget::item:selected {{
    background-color: {C_SELECTION};
}}
QTreeWidget QHeaderView::section {{
    background-color: {C_SURFACE};
    border: none;
    border-bottom: 1px solid {C_BORDER};
    padding: 6px 8px;
}}

/* ── 表格 ── */
QTableWidget {{
    background-color: {C_SURFACE};
    alternate-background-color: {C_ROW_ALT};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    gridline-color: {C_BORDER};
    outline: none;
}}
QTableWidget::item {{
    padding: 5px 8px;
    border-bottom: 1px solid transparent;
}}
QTableWidget::item:hover {{
    background-color: {C_SURFACE_RAISED};
}}
QTableWidget::item:selected {{
    background-color: {C_SELECTION};
}}
QTableWidget QHeaderView::section {{
    background-color: {C_SURFACE};
    border: none;
    border-bottom: 2px solid {C_BORDER};
    padding: 7px 8px;
}}
QHeaderView::down-arrow {{
    subcontrol-position: center right;
    padding-right: 6px;
}}

/* ── 下拉框 ── */
QComboBox {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {C_BORDER_FOCUS};
}}
QComboBox:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    selection-background-color: {C_SELECTION};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 5px 8px;
}}

/* ── 按钮 ── */
QPushButton {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    padding: 6px 16px;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: #2c2923;
    border-color: {C_BORDER_FOCUS};
}}
QPushButton:pressed {{
    background-color: #1e1c18;
}}
QPushButton:disabled {{
    color: {C_TEXT_MUTED};
}}

/* ── 开始按钮 ── */
QPushButton.accent {{
    background-color: {C_ACCENT};
    color: {C_BASE};
    border: none;
    font-weight: bold;
    font-size: 14px;
    padding: 10px 24px;
}}
QPushButton.accent:hover {{
    background-color: {C_ACCENT_HOVER};
}}
QPushButton.accent:pressed {{
    background-color: #b88730;
}}

/* ── 输入框 ── */
QLineEdit {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 5px 8px;
}}
QLineEdit:focus {{
    border-color: {C_ACCENT};
}}

/* ── 数字框 ── */
QSpinBox {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 28px 4px 8px;
}}
QSpinBox:focus {{
    border-color: {C_ACCENT};
}}

/* ── 复选框 ── */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    background-color: {C_SURFACE_RAISED};
}}
QCheckBox::indicator:checked {{
    background-color: {C_ACCENT};
    border-color: {C_ACCENT};
}}

/* ── 组框 ── */
QGroupBox {{
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    padding: 0 8px;
    color: {C_TEXT_SECONDARY};
}}

/* ── 进度条 ── */
QProgressBar {{
    background-color: {C_PROGRESS_BG};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    text-align: center;
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {C_PROGRESS_CHUNK};
    border-radius: 3px;
}}

/* ── 状态栏 ── */
QStatusBar {{
    background-color: {C_SURFACE};
    border-top: 1px solid {C_BORDER};
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    padding: 2px 12px;
    color: {C_TEXT_SECONDARY};
}}

/* ── 菜单 ── */
QMenuBar {{
    background-color: {C_SURFACE};
    border-bottom: 1px solid {C_BORDER};
}}
QMenuBar::item {{
    padding: 4px 10px;
}}
QMenuBar::item:selected {{
    background-color: {C_SURFACE_RAISED};
}}
QMenu {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: {C_SURFACE_RAISED};
}}
QMenu::separator {{
    height: 1px;
    background: {C_BORDER};
    margin: 4px 8px;
}}

/* ── 滚动条 ── */
QScrollBar:vertical {{
    background: {C_BASE};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_TEXT_MUTED};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {C_BASE};
    height: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {C_BORDER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Dock ── */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {C_SURFACE};
    border-bottom: 1px solid {C_BORDER};
    padding: 6px 10px;
    text-align: left;
}}

/* ── 工具提示 ── */
QToolTip {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    color: {C_TEXT};
}}

/* ── 文件对话框按钮 ── */
QToolButton {{
    background-color: {C_SURFACE_RAISED};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    border-color: {C_BORDER_FOCUS};
}}
"""


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
