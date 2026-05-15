"""PresetCardPanel 单元测试"""
import pytest
from PySide6.QtCore import Qt

from leanreel.core.strategy import Strategy
from leanreel.gui.strategy_panel import PresetCardPanel


# ── 测试数据工厂 ──────────────────────────────────────────────

def _make_strategies():
    """创建 3 个非平凡策略 — 每个都有不同编码器、CRF、预估节省和描述"""
    return [
        Strategy.from_dict({
            "name": "均衡压缩",
            "description": "视觉无损，适合大多数场景",
            "is_preset": True,
            "video": {
                "encoder": "libx265", "crf": 20, "preset": "slow",
                "pix_fmt": "yuv420p10le",
            },
            "filters": {"skip_x265": True, "min_size_gb": None},
            "estimated_savings": "35-50%",
            "quality_impact": "视觉无损，HDR/DV完整保留",
        }),
        Strategy.from_dict({
            "name": "极限压缩",
            "description": "最大化压缩率，轻微质量损失",
            "is_preset": True,
            "video": {
                "encoder": "libx265", "crf": 22, "preset": "slower",
                "pix_fmt": "yuv420p10le",
            },
            "filters": {"skip_x265": False, "min_size_gb": 1.0},
            "estimated_savings": "50-70%",
            "quality_impact": "轻微色带，暗部细节略损",
        }),
        Strategy.from_dict({
            "name": "轻量压缩",
            "description": "最小压缩，最高质量保留",
            "is_preset": True,
            "video": {
                "encoder": "libx264", "crf": 18, "preset": "fast",
                "pix_fmt": "yuv420p",
            },
            "filters": {"skip_x265": True, "min_size_gb": 2.0},
            "estimated_savings": "10-20%",
            "quality_impact": "几乎无损",
        }),
    ]


def _make_strategies_distinct():
    """创建 5 个差异显著的策略 — 用于测试替换场景"""
    return [
        Strategy.from_dict({
            "name": "策略A",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "libx265", "crf": 15},
            "filters": {},
            "estimated_savings": "30%",
        }),
        Strategy.from_dict({
            "name": "策略B",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "libx264", "crf": 16},
            "filters": {},
            "estimated_savings": "25%",
        }),
        Strategy.from_dict({
            "name": "策略C",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "hevc_nvenc", "crf": 20},
            "filters": {},
            "estimated_savings": "40%",
        }),
        Strategy.from_dict({
            "name": "策略D",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "h264_nvenc", "crf": 22},
            "filters": {},
            "estimated_savings": "45%",
        }),
        Strategy.from_dict({
            "name": "策略E",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "copy", "crf": 0},
            "filters": {},
            "estimated_savings": "0%",
        }),
    ]


# ── set_strategies 测试 ──────────────────────────────────────

class TestSetStrategies:
    """set_strategies() 方法的全面测试"""

    def test_creates_correct_number_of_cards(self, qtbot):
        """传入 3 个策略，应创建 3 张卡片"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        buttons = panel.card_group.buttons()
        assert len(buttons) == 3

    def test_card_text_contains_strategy_names(self, qtbot):
        """每张卡片的文本应包含对应策略的名称"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        buttons = panel.card_group.buttons()
        button_texts = [btn.text() for btn in buttons]
        for s in strategies:
            assert any(s.name in text for text in button_texts), (
                f"策略名称 '{s.name}' 未在任何卡片文本中找到: {button_texts}"
            )

    def test_description_label_shows_selected_strategy_description(self, qtbot):
        """描述独立显示在 description_label 中，选中哪个策略就显示哪个的描述"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        # 默认选中第一个策略，描述标签应显示其描述
        assert panel.description_label.isVisibleTo(panel)
        assert "视觉无损" in panel.description_label.text(), (
            f"描述标签应包含首个策略的描述: {panel.description_label.text()}"
        )

        # 点击第二个策略，描述标签应更新
        panel.card_group.buttons()[1].click()
        assert panel.description_label.isVisibleTo(panel)
        assert "最大化压缩率" in panel.description_label.text(), (
            f"描述标签应更新为第二个策略的描述: {panel.description_label.text()}"
        )

        # 描述不应出现在紧凑按钮文本中
        button_texts = [btn.text() for btn in panel.card_group.buttons()]
        for text in button_texts:
            assert "视觉无损" not in text, (
                f"描述不应出现在按钮文本中（应紧凑显示）: {text}"
            )

    def test_description_label_hides_for_empty_description(self, qtbot):
        """当选中策略无描述时，description_label 应隐藏"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        no_desc_strategies = _make_strategies_distinct()  # 这些策略的 description 为空

        panel.set_strategies(no_desc_strategies)
        assert not panel.description_label.isVisibleTo(panel), "空描述时标签应隐藏"

        # 点击另一个空描述策略，标签仍应隐藏
        panel.card_group.buttons()[1].click()
        assert not panel.description_label.isVisibleTo(panel)

    def test_card_text_contains_estimated_savings(self, qtbot):
        """卡片文本应包含预估节省信息"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        buttons = panel.card_group.buttons()
        button_texts = [btn.text() for btn in buttons]
        for s in strategies:
            assert any(s.estimated_savings in text for text in button_texts), (
                f"预估节省 '{s.estimated_savings}' 未在任何卡片文本中找到"
            )

    def test_strategy_rows_use_two_line_technical_layout(self, qtbot):
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = [
            Strategy.from_dict({
                "name": "x265 HEVC CRF 18 高质量转码",
                "description": "CPU x265 慢速高质量，适合值得保留细节的 SDR H.264 片源。",
                "is_preset": True,
                "video": {"encoder": "libx265", "crf": 18, "preset": "slow"},
                "estimated_savings": "20-35%",
            }),
        ]

        panel.set_strategies(strategies)

        button = panel.card_group.buttons()[0]
        assert "x265 HEVC CRF 18 高质量转码" in button.text()
        assert "\n" in button.text()
        assert "CPU" in button.text()
        assert "20-35%" in button.text()
        assert button.minimumHeight() >= 42

    def test_default_first_card_is_checked(self, qtbot):
        """第一个策略应默认选中"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        buttons = panel.card_group.buttons()
        assert buttons[0].isChecked(), "第一个卡片应该被选中"
        for i, btn in enumerate(buttons[1:], start=1):
            assert not btn.isChecked(), f"卡片 {i} 不应该被选中"

    def test_empty_list_does_not_crash(self, qtbot):
        """传入空列表不应崩溃"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)

        # 不应抛出任何异常
        panel.set_strategies([])
        assert len(panel.card_group.buttons()) == 0

    def test_replaces_existing_cards_with_new_strategies(self, qtbot):
        """第二次调用 set_strategies 应替换旧卡片"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)

        # 第一次设置 3 个策略
        panel.set_strategies(_make_strategies())
        assert len(panel.card_group.buttons()) == 3

        # 第二次设置不同的 5 个策略
        new_strategies = _make_strategies_distinct()
        panel.set_strategies(new_strategies)

        buttons = panel.card_group.buttons()
        assert len(buttons) == 5, f"应该有 5 张新卡片，实际有 {len(buttons)} 张"
        button_texts = [btn.text() for btn in buttons]
        for s in new_strategies:
            assert any(s.name in text for text in button_texts), (
                f"新策略名称 '{s.name}' 未在卡片文本中找到"
            )

    def test_selection_resets_to_first_after_replace(self, qtbot):
        """替换策略列表后，选中应重置为第一个"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)
        # 点击第三个卡片
        panel.card_group.buttons()[2].click()
        assert panel._active_preset_index == 2
        assert not panel.card_group.buttons()[0].isChecked()
        assert panel.card_group.buttons()[2].isChecked()

        # 再次设置（相同策略），应重置为第一个
        panel.set_strategies(strategies)
        assert panel._active_preset_index == 0
        assert panel.card_group.buttons()[0].isChecked()
        for i, btn in enumerate(panel.card_group.buttons()[1:], start=1):
            assert not btn.isChecked(), f"卡片 {i} 不应该被选中"

    def test_gpu_strategy_shows_gpu_tag(self, qtbot):
        """GPU 编码器的策略应在卡片显示 [GPU] 标签"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        gpu_strategy = Strategy.from_dict({
            "name": "GPU 加速",
            "description": "",
            "is_preset": True,
            "video": {"encoder": "hevc_nvenc", "crf": 23},
            "filters": {},
            "estimated_savings": "40%",
        })

        panel.set_strategies([gpu_strategy])
        assert len(panel.card_group.buttons()) == 1
        assert "[GPU]" in panel.card_group.buttons()[0].text()


# ── current_preset_strategy 测试 ─────────────────────────────

class TestCurrentPresetStrategy:
    """current_preset_strategy 属性的全面测试"""

    def test_returns_first_strategy_by_default(self, qtbot):
        """未手动选择时，应返回第一个策略"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)

        current = panel.current_preset_strategy
        assert current is not None
        assert current is strategies[0]
        assert current.name == "均衡压缩"

    def test_returns_updated_strategy_after_click(self, qtbot):
        """点击第二张卡片后，应返回对应策略"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)
        panel.card_group.buttons()[1].click()

        current = panel.current_preset_strategy
        assert current is strategies[1]
        assert current.name == "极限压缩"

    def test_returns_third_strategy_after_click(self, qtbot):
        """点击第三张卡片后，应返回第三个策略"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)
        panel.card_group.buttons()[2].click()

        current = panel.current_preset_strategy
        assert current is strategies[2]
        assert current.name == "轻量压缩"
        assert current.video.crf == 18

    def test_returns_none_when_no_strategies(self, qtbot):
        """未设置策略时，应返回 None"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)

        assert panel.current_preset_strategy is None

    def test_returns_none_after_emptying_strategies(self, qtbot):
        """设置策略后再清空，应返回 None"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        panel.set_strategies(strategies)
        assert panel.current_preset_strategy is not None

        panel.set_strategies([])
        assert panel.current_preset_strategy is None


# ── strategy_changed 信号测试 ────────────────────────────────

class TestStrategyChangedSignal:
    """strategy_changed 信号的全面测试"""

    def test_emits_on_card_click(self, qtbot):
        """点击卡片时应发射 strategy_changed 信号，参数为正确的索引"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        with qtbot.waitSignal(panel.strategy_changed, timeout=1000) as blocker:
            panel.card_group.buttons()[1].click()

        assert blocker.args == [1], f"信号参数应为 [1]，实际为 {blocker.args}"

    def test_emits_with_correct_index_for_third_card(self, qtbot):
        """点击第三个卡片，信号参数应为 2"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        with qtbot.waitSignal(panel.strategy_changed, timeout=1000) as blocker:
            panel.card_group.buttons()[2].click()

        assert blocker.args == [2], f"信号参数应为 [2]，实际为 {blocker.args}"

    def test_emits_when_clicking_already_selected_card(self, qtbot):
        """点击已选中的卡片也应发射信号"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        # 第一个卡片默认已选中，再点一次
        with qtbot.waitSignal(panel.strategy_changed, timeout=1000) as blocker:
            panel.card_group.buttons()[0].click()

        assert blocker.args == [0]

    def test_set_strategies_does_not_emit_strategy_changed(self, qtbot):
        """Qt 文档明确：setChecked() 不会发射 clicked() 信号，
        因此 set_strategies（仅调用 setChecked）不应触发 strategy_changed"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()

        signals_received = []
        panel.strategy_changed.connect(lambda idx: signals_received.append(idx))
        panel.set_strategies(strategies)

        assert signals_received == [], (
            f"set_strategies 不应发射 strategy_changed，但收到: {signals_received}"
        )

    def test_multiple_clicks_emit_multiple_signals(self, qtbot):
        """多次点击不同卡片应发射多次信号"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        signals_received = []
        panel.strategy_changed.connect(lambda idx: signals_received.append(idx))

        panel.card_group.buttons()[1].click()
        panel.card_group.buttons()[2].click()
        panel.card_group.buttons()[0].click()

        assert signals_received == [1, 2, 0], (
            f"应收到信号序列 [1, 2, 0]，实际收到 {signals_received}"
        )


# ── _update_card_indicators 测试 ─────────────────────────────

class TestUpdateCardIndicators:
    """_update_card_indicators() 的间接测试（通过点击卡片触发）"""

    def test_active_card_shows_filled_circle_prefix(self, qtbot):
        """选中的卡片应显示 ● 前缀"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        # 默认第一个选中
        text0 = panel.card_group.buttons()[0].text()
        assert "●" in text0, f"第一个选中的卡片文本中应含 ●: {text0}"

        # 没有选中的卡片应有 ○
        text1 = panel.card_group.buttons()[1].text()
        text2 = panel.card_group.buttons()[2].text()
        assert "○" in text1, f"未选中的卡片文本中应含 ○: {text1}"
        assert "○" in text2, f"未选中的卡片文本中应含 ○: {text2}"

    def test_prefix_swaps_after_clicking_another_card(self, qtbot):
        """点击另一个卡片后，新旧选中的前缀应互换"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        # 点击第二个卡片
        panel.card_group.buttons()[1].click()

        # 新选中的应有 ●
        text1 = panel.card_group.buttons()[1].text()
        assert "●" in text1, f"点击后选中的卡片文本应含 ●: {text1}"

        # 旧选中的应有 ○
        text0 = panel.card_group.buttons()[0].text()
        assert "○" in text0, f"取消选中的卡片文本应含 ○: {text0}"

        # 第三个仍为 ○
        text2 = panel.card_group.buttons()[2].text()
        assert "○" in text2, f"未点击的卡片文本应含 ○: {text2}"

    def test_only_one_card_checked_at_a_time(self, qtbot):
        """QButtonGroup exclusive 模式确保同一时间只有一张卡片被选中"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        # 逐一点击所有卡片，每次只有一张被选中
        for click_idx in range(3):
            panel.card_group.buttons()[click_idx].click()
            checked_count = sum(
                1 for i, btn in enumerate(panel.card_group.buttons())
                if btn.isChecked()
            )
            assert checked_count == 1, (
                f"点击卡片 {click_idx} 后应有恰好 1 张卡片被选中，"
                f"实际 {checked_count} 张"
            )
            assert panel.card_group.buttons()[click_idx].isChecked(), (
                f"被点击的卡片 {click_idx} 应该被选中"
            )

    def test_checked_state_matches_active_index(self, qtbot):
        """btn.isChecked() 状态应与 _active_preset_index 一致"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        for click_idx in [1, 2, 0, 2, 1]:
            panel.card_group.buttons()[click_idx].click()
            for i, btn in enumerate(panel.card_group.buttons()):
                if i == click_idx:
                    assert btn.isChecked(), (
                        f"卡片 {i} 应该被选中 (active={panel._active_preset_index})"
                    )
                else:
                    assert not btn.isChecked(), (
                        f"卡片 {i} 不应该被选中 (active={panel._active_preset_index})"
                    )

    def test_indicators_synchronize_with_strategy_names(self, qtbot):
        """切换选中后，卡片文本仍包含正确的策略名称"""
        panel = PresetCardPanel()
        qtbot.addWidget(panel)
        strategies = _make_strategies()
        panel.set_strategies(strategies)

        # 点击第二张卡片
        panel.card_group.buttons()[1].click()

        # 检查所有卡片的文本仍包含对应的策略名称
        for i, s in enumerate(strategies):
            assert s.name in panel.card_group.buttons()[i].text(), (
                f"卡片 {i} 应包含策略名称 '{s.name}'"
            )
