"""策略面板 — 紧凑单选式预设选择 + 可折叠自定义参数 + 编码设置"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QLabel, QSpinBox,
    QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QFileDialog, QHBoxLayout, QToolButton,
    QButtonGroup, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Signal, QPropertyAnimation, QEasingCurve

from leanreel.domain.models import Strategy
from leanreel.ui_text import UI_TEXT
from leanreel.gui.theme import (
    C_SURFACE, C_SURFACE_RAISED, C_SURFACE_LOWERED,
    C_BORDER, C_BORDER_FOCUS, C_ACCENT, C_ACCENT_LIGHT,
    C_SELECTION, C_TEXT, C_TEXT_SECONDARY, C_TEXT_TERTIARY, C_TEXT_DISABLED,
    C_STRATEGY_TEXT, C_STRATEGY_CHECKED_TEXT,
    C_STRATEGY_CHECKED_HOVER_BG, C_STRATEGY_HOVER_BORDER,
)

_CPU_ENCODERS = ["libx265"]
_GPU_ENCODERS = ["av1_nvenc", "hevc_nvenc", "h264_nvenc"]
_ALL_ENCODERS = [*_CPU_ENCODERS, *_GPU_ENCODERS, "copy"]
_NV_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
_GPU_CQ_MAX = {"av1_nvenc": 63, "hevc_nvenc": 51, "h264_nvenc": 51}
_GPU_CUSTOM_NAMES = {
    "av1_nvenc": "AV1 NVENC CQ {cq} 自定义转码",
    "hevc_nvenc": "HEVC NVENC CQ {cq} 自定义转码",
    "h264_nvenc": "H.264 NVENC CQ {cq} 自定义转码",
}

_ROW_STYLE = f"""
QPushButton {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    text-align: left;
    min-height: 42px;
    font-size: 9pt;
    color: {C_STRATEGY_TEXT};
}}
QPushButton:hover {{
    border-color: {C_BORDER_FOCUS};
    background-color: {C_SURFACE_RAISED};
}}
QPushButton:checked {{
    border: 1px solid {C_ACCENT_LIGHT};
    background-color: {C_SELECTION};
    color: {C_STRATEGY_CHECKED_TEXT};
}}
QPushButton:checked:hover {{
    border-color: {C_STRATEGY_HOVER_BORDER};
    background-color: {C_STRATEGY_CHECKED_HOVER_BG};
}}
"""


class PresetCardPanel(QWidget):
    """预设策略选择面板 — 紧凑单选行 + 独立描述标签

    将原来的大卡片改为紧凑的单选按钮行，每行仅显示：
      ● 策略名  [CPU/GPU/COPY]  节省率
    描述文字独立显示在策略列表下方的 QLabel 中。
    """

    strategy_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self._strategies = []
        self._active_preset_index = 0
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        presets_label = QLabel(UI_TEXT.STRATEGY_PRESETS)
        presets_label.setStyleSheet(
            f"font-weight: bold; color: {C_TEXT_SECONDARY}; font-size: 9pt; padding: 2px 4px;"
        )
        layout.addWidget(presets_label)

        # 按钮容器 — 每条策略一行紧凑按钮
        self.button_area = QWidget()
        self.button_layout = QVBoxLayout(self.button_area)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(2)
        layout.addWidget(self.button_area)

        # 描述标签 — 独立显示当前选中策略的描述
        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(
            f"color: {C_TEXT_TERTIARY}; font-size: 9pt; padding: 4px 8px;"
            f"background: {C_SURFACE_LOWERED}; border-radius: 4px;"
            f"border: 1px solid {C_BORDER};"
        )
        self.description_label.hide()
        layout.addWidget(self.description_label)

        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)

    def _make_row_button(self, s: Strategy, index: int) -> QPushButton:
        tag = "GPU" if s.video.is_gpu else ("CPU" if s.video.encoder.startswith("lib")
                                             else "COPY")
        savings = getattr(s, "estimated_savings", "") or ""
        text = f"{s.name}\n   [{tag}]  {savings}"

        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setStyleSheet(_ROW_STYLE)
        btn.setMinimumHeight(44)
        btn.setToolTip(f"{s.name}\n{s.description}".strip())
        btn.setAccessibleName(f"策略: {s.name}")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.clicked.connect(lambda checked=False, i=index: self._on_card_clicked(i))
        return btn

    def set_strategies(self, strategies: list):
        self._strategies = strategies

        # 清除旧按钮
        for btn in self.card_group.buttons():
            self.card_group.removeButton(btn)

        while self.button_layout.count() > 0:
            item = self.button_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 创建新按钮
        for i, s in enumerate(strategies):
            btn = self._make_row_button(s, i)
            self.card_group.addButton(btn, i)
            self.button_layout.addWidget(btn)

        if strategies:
            self.card_group.buttons()[0].setChecked(True)
            self._active_preset_index = 0
            self._update_indicators()
            self._update_description()
        else:
            self.description_label.hide()

    def _on_card_clicked(self, index: int):
        self._active_preset_index = index
        self._update_indicators()
        self._update_description()
        self.strategy_changed.emit(index)

    def _update_indicators(self):
        """更新所有按钮的 checked 状态（CSS 自动处理选中样式）"""
        for i, btn in enumerate(self.card_group.buttons()):
            btn.setChecked(i == self._active_preset_index)
            if i == self._active_preset_index:
                btn.setAccessibleName(f"已选中: {self._strategies[i].name}")
            else:
                btn.setAccessibleName(f"策略: {self._strategies[i].name}")

    def _update_description(self):
        """根据当前选中的策略更新描述标签"""
        idx = self._active_preset_index
        if 0 <= idx < len(self._strategies):
            desc = getattr(self._strategies[idx], "description", "") or ""
            if desc.strip():
                self.description_label.setText(f"  {desc}")
                self.description_label.show()
            else:
                self.description_label.hide()
        else:
            self.description_label.hide()

    def select_by_strategy(self, name: str):
        """根据策略名选中对应按钮，不触发 strategy_changed 信号。"""
        for i, s in enumerate(self._strategies):
            if s.name == name:
                self._active_preset_index = i
                self._update_indicators()
                self._update_description()
                return

    @property
    def current_preset_strategy(self):
        idx = self._active_preset_index
        if 0 <= idx < len(self._strategies):
            return self._strategies[idx]
        return None


class CollapsibleGroup(QGroupBox):
    """可折叠的 QGroupBox — 点击标题栏复选框以动画方式展开/收起内容"""

    _ANIM_DURATION = 250  # ms，符合 product register 150-250ms 规范

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(False)
        self._content = None
        self._anim = None
        self.setStyleSheet(f"""
            QGroupBox {{
                padding-top: 16px;
                margin-top: 4px;
                font-weight: bold;
                color: {C_TEXT_SECONDARY};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
            QGroupBox::indicator {{
                width: 12px;
                height: 12px;
            }}
        """)

    def set_content_widget(self, widget: QWidget):
        """设置内容 widget，折叠时以动画方式隐藏"""
        self._content = widget
        # 将 content widget 添加到 group box 的布局中
        if self.layout() is None:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(4, 4, 4, 4)
            main_layout.addWidget(widget)
        else:
            self.layout().addWidget(widget)
        widget.setVisible(False)
        self.toggled.connect(self._animate_toggle)

    def _measure_content_height(self) -> int:
        """测量内容 widget 的目标高度。"""
        self._content.setVisible(True)
        self._content.adjustSize()
        h = self._content.sizeHint().height()
        self._content.setVisible(False)
        return max(h, 60)  # 最小 60px，避免零高度

    def _animate_toggle(self, checked: bool):
        """动画展开/收起内容区域。"""
        if self._content is None:
            return

        # 停止正在进行的动画
        if self._anim is not None and self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()

        target = self._measure_content_height()

        self._anim = QPropertyAnimation(self._content, b"maximumHeight")
        self._anim.setDuration(self._ANIM_DURATION)
        self._anim.setEasingCurve(QEasingCurve.OutQuart)

        if checked:
            self._content.setVisible(True)
            self._content.setMaximumHeight(0)
            self._anim.setStartValue(0)
            self._anim.setEndValue(target)
            self._anim.finished.connect(lambda: self._on_expand_done())
        else:
            self._content.setMaximumHeight(target)
            self._anim.setStartValue(target)
            self._anim.setEndValue(0)
            self._anim.finished.connect(lambda: self._on_collapse_done())

        self._anim.start()

    def _on_expand_done(self):
        """展开完成：移除高度限制，让内容随布局自适应。"""
        if self._content:
            self._content.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

    def _on_collapse_done(self):
        """收起完成：隐藏内容 widget。"""
        if self._content:
            self._content.setVisible(False)


class StrategyPanel(QWidget):
    """策略面板 — PresetCardPanel + 可折叠自定义参数 + 编码设置 + 开始按钮"""

    start_requested = Signal()
    strategy_changed = Signal(int)
    custom_strategy_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── 预设选择（紧凑单选行）──
        self.preset_panel = PresetCardPanel()
        self.preset_panel.strategy_changed.connect(self.strategy_changed.emit)
        layout.addWidget(self.preset_panel)

        # ── 自定义参数（可折叠）──
        self.custom_group = CollapsibleGroup(UI_TEXT.STRATEGY_CUSTOM_GROUP)

        custom_content = QWidget()
        custom_layout = QFormLayout(custom_content)
        custom_layout.setContentsMargins(4, 0, 4, 0)
        custom_layout.setVerticalSpacing(6)

        self.custom_encoder_combo = QComboBox()
        self.custom_encoder_combo.addItems(_ALL_ENCODERS)
        self.custom_encoder_combo.currentIndexChanged.connect(self._on_encoder_changed)

        self.custom_crf_spin = QSpinBox()
        self.custom_crf_spin.setRange(0, 51)
        self.custom_crf_spin.setValue(20)
        self.crf_label = QLabel("CRF")
        self.crf_label.setToolTip(UI_TEXT.STRATEGY_CRF_TOOLTIP)

        self.custom_cq_spin = QSpinBox()
        self.custom_cq_spin.setRange(0, 63)
        self.custom_cq_spin.setValue(34)
        self.cq_label = QLabel("CQ")

        self.custom_nvpreset_combo = QComboBox()
        self.custom_nvpreset_combo.addItems([p.upper() for p in _NV_PRESETS])
        self.custom_nvpreset_combo.setCurrentText("P7")
        self.nvpreset_label = QLabel(UI_TEXT.STRATEGY_NV_PRESET)

        self.custom_audio_combo = QComboBox()
        self.custom_audio_combo.addItems(["keep_original", "strip_commentary"])
        self.custom_subtitle_combo = QComboBox()
        self.custom_subtitle_combo.addItems(
            ["keep_all", "keep_chinese", "keep_chinese_english", "remove_all"]
        )
        self.custom_savings_label = QLabel(UI_TEXT.STRATEGY_ESTIMATED_SAVINGS_DEFAULT)

        custom_layout.addRow(UI_TEXT.STRATEGY_ENCODER, self.custom_encoder_combo)
        custom_layout.addRow(self.crf_label, self.custom_crf_spin)
        custom_layout.addRow(self.cq_label, self.custom_cq_spin)
        custom_layout.addRow(self.nvpreset_label, self.custom_nvpreset_combo)
        custom_layout.addRow(UI_TEXT.STRATEGY_AUDIO, self.custom_audio_combo)
        custom_layout.addRow(UI_TEXT.STRATEGY_SUBTITLE, self.custom_subtitle_combo)
        custom_layout.addRow(self.custom_savings_label)

        self.custom_group.set_content_widget(custom_content)
        layout.addWidget(self.custom_group)

        # 信号连接 — 自定义参数变化时重新计算策略
        for widget in (
            self.custom_encoder_combo,
            self.custom_crf_spin,
            self.custom_cq_spin,
            self.custom_nvpreset_combo,
            self.custom_audio_combo, self.custom_subtitle_combo,
        ):
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._emit_custom_strategy)
            else:
                widget.valueChanged.connect(self._emit_custom_strategy)

        # ── 编码设置 ──
        encode_group = QGroupBox(UI_TEXT.STRATEGY_ENCODING_SETTINGS)
        encode_group.setStyleSheet(f"""
            QGroupBox {{
                padding-top: 16px;
                margin-top: 4px;
                font-weight: bold;
                color: {C_TEXT_SECONDARY};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        encode_layout = QFormLayout(encode_group)
        encode_layout.setContentsMargins(8, 4, 8, 4)
        encode_layout.setVerticalSpacing(6)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(2)
        self.workers_spin.setSuffix(UI_TEXT.STRATEGY_WORKERS_SUFFIX)
        encode_layout.addRow(UI_TEXT.STRATEGY_WORKERS, self.workers_spin)

        self.delete_source_cb = QCheckBox(UI_TEXT.STRATEGY_DELETE_SOURCE)
        self.delete_source_cb.setChecked(False)
        encode_layout.addRow(self.delete_source_cb)

        layout.addWidget(encode_group)

        # ── 开始按钮 ──
        self.start_btn = QPushButton(UI_TEXT.STRATEGY_START)
        self.start_btn.setObjectName("primary_action")
        self.start_btn.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_btn)
        self._on_encoder_changed()

    def set_strategies(self, strategies: list):
        self.preset_panel.set_strategies(strategies)
        self.custom_group.setChecked(False)

    def show_custom_strategy(self):
        self.custom_group.setChecked(True)
        self._emit_custom_strategy()

    def show_preset_strategy(self):
        self.custom_group.setChecked(False)

    def _on_encoder_changed(self):
        encoder = self.custom_encoder_combo.currentText()
        is_cpu = encoder in _CPU_ENCODERS
        is_gpu = encoder in _GPU_ENCODERS

        self.crf_label.setVisible(is_cpu)
        self.custom_crf_spin.setVisible(is_cpu)
        self.cq_label.setVisible(is_gpu)
        self.custom_cq_spin.setVisible(is_gpu)
        self.nvpreset_label.setVisible(is_gpu)
        self.custom_nvpreset_combo.setVisible(is_gpu)
        if is_gpu:
            self.custom_cq_spin.setRange(0, _GPU_CQ_MAX.get(encoder, 51))

        self._emit_custom_strategy()

    def _emit_custom_strategy(self):
        strategy = self.custom_strategy
        self.custom_savings_label.setText(
            UI_TEXT.estimated_savings(strategy.estimated_savings)
        )
        self.custom_strategy_changed.emit(strategy)

    @property
    def custom_strategy(self):
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS
        is_cpu = encoder in _CPU_ENCODERS
        is_copy = encoder == "copy"

        if is_copy:
            name = UI_TEXT.STRATEGY_COPY_CUSTOM_NAME
            savings = "5-15%"
            quality_impact = UI_TEXT.STRATEGY_COPY_QUALITY
            crf_val = 0
            cq_val = 0
        elif is_cpu:
            crf_val = self.custom_crf_spin.value()
            cq_val = 0
            name = UI_TEXT.STRATEGY_CPU_CUSTOM_NAME.format(crf=crf_val)
            quality_impact = UI_TEXT.STRATEGY_CPU_QUALITY
            if crf_val <= 18:
                savings = "20-35%"
            elif crf_val <= 20:
                savings = "35-50%"
            elif crf_val <= 22:
                savings = "50-70%"
            else:
                savings = "60-75%"
        else:
            crf_val = 0
            cq_val = self.custom_cq_spin.value()
            name = _GPU_CUSTOM_NAMES.get(
                encoder,
                UI_TEXT.STRATEGY_GPU_CUSTOM_NAME,
            ).format(cq=cq_val)
            quality_impact = UI_TEXT.STRATEGY_GPU_QUALITY
            if encoder == "av1_nvenc":
                if cq_val <= 32:
                    savings = "35-55%"
                elif cq_val <= 34:
                    savings = "45-65%"
                else:
                    savings = "50-70%"
            elif cq_val <= 20:
                savings = "15-30%"
            elif cq_val <= 24:
                savings = "25-45%"
            elif cq_val <= 28:
                savings = "35-55%"
            else:
                savings = "45-65%"

        nv_preset = self.custom_nvpreset_combo.currentText().lower()

        return Strategy.from_dict({
            "name": name,
            "description": UI_TEXT.STRATEGY_MANUAL_DESCRIPTION,
            "is_preset": False,
            "video": {
                "encoder": encoder,
                "crf": crf_val,
                "preset": "slow" if is_cpu else "",
                "pix_fmt": "yuv420p10le",
                "gpu": is_gpu,
                "nv_preset": nv_preset if is_gpu else "",
                "rc": "vbr" if is_gpu else "",
                "cq": cq_val,
            },
            "audio": {"mode": self.custom_audio_combo.currentText()},
            "subtitle": {"mode": self.custom_subtitle_combo.currentText()},
            "filters": {"skip_x265": False},
            "estimated_savings": savings,
            "quality_impact": quality_impact,
        })

    @property
    def worker_count(self) -> int:
        return self.workers_spin.value()

    @property
    def delete_source(self) -> bool:
        return self.delete_source_cb.isChecked()

    @property
    def current_strategy(self):
        if self.custom_group.isChecked():
            return self.custom_strategy
        return self.current_preset_strategy

    @property
    def current_preset_strategy(self):
        return self.preset_panel.current_preset_strategy
