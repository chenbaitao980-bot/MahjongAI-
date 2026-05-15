from __future__ import annotations

import html
import re
from copy import deepcopy

from PyQt6.QtCore import pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from battle.service import (
    QWEN_VISION_SYSTEM_PROMPT,
    QWEN_VISION_USER_PROMPT_TEMPLATE,
    VOLC_VISION_PROMPT_TEMPLATE,
)
from battle.state import BattleAdvice, BattleState, meld_from_ids, tile_from_id
from game.state import ALL_TILE_IDS, MeldGroup


_C_SELF  = "#74c69d"   # 自家回合（绿）
_C_ENEMY = "#e07a5f"   # 敌方回合（暖橙红）
_C_OK    = "#52b788"   # 成功/推荐（护眼绿）
_C_WARN  = "#f4a261"   # 警告（暖橙）
_C_ERR   = "#e07a5f"   # 错误（暖红）
_C_AI    = "#b5a0d4"   # AI生成中（柔紫）
_C_CAND  = "#5bc0be"   # 候选动作（青绿）
_C_GOLD  = "#e9c46a"   # 暖黄（选中高亮）
_C_MUTED = "#5a7868"   # 弱文字
_C_2ND   = "#7aaa8a"   # 次文字
_C_TEXT  = "#ccddd5"   # 主文字

TILE_NAME_MAP = {
    **{f"{i}m": f"{i}万" for i in range(1, 10)},
    **{f"{i}p": f"{i}筒" for i in range(1, 10)},
    **{f"{i}s": f"{i}条" for i in range(1, 10)},
    "1z": "东",
    "2z": "南",
    "3z": "西",
    "4z": "北",
    "5z": "中",
    "6z": "发",
    "7z": "白",
}

SUIT_OPTIONS = [
    ("m", "万"),
    ("p", "筒"),
    ("s", "条"),
    ("z", "字"),
]

HONOR_OPTIONS = [
    ("1z", "东"),
    ("2z", "南"),
    ("3z", "西"),
    ("4z", "北"),
    ("5z", "中"),
    ("6z", "发"),
    ("7z", "白"),
]

MELD_TYPE_OPTIONS = [
    ("chi", "吃"),
    ("pon", "碰"),
    ("kan_open", "明杠"),
    ("kan_closed", "暗杠"),
    ("kan_added", "补杠"),
]

CONSOLE_LINKS = {
    "deepseek": ("DeepSeek 控制台", "https://platform.deepseek.com/api_keys"),
    "volc": ("火山方舟控制台", "https://console.volcengine.com/ark"),
    "qwen": ("阿里百炼控制台", "https://bailian.console.aliyun.com/"),
    "glm": ("智谱控制台", "https://open.bigmodel.cn/usercenter/apikeys"),
}

PROVIDER_LABELS = {
    "auto": "智能选择（火山优先）",
    "volc": "火山方舟 Doubao",
    "qwen": "阿里百炼 Qwen",
    "glm": "智谱 GLM",
}

# 阿里百炼视觉模型列表（可在此处追加新模型）
QWEN_VISION_MODELS = [
    "qwen3-vl-plus",
    "qwen-vl-plus-latest",
    "qwen-vl-plus",
    "qwen-vl-max-latest",
    "qwen-vl-max",
    "qwen2.5-vl-72b-instruct",
    "qwen2.5-vl-7b-instruct",
    "qwen2.5-vl-3b-instruct",
    "qwen2-vl-72b-instruct",
    "qwen2-vl-7b-instruct",
]


def tile_display(tile_id: str) -> str:
    return TILE_NAME_MAP.get(tile_id, tile_id)


def _replace_tile_codes(text: str) -> str:
    """将文本中的牌代码（如3p、7m、9s、1z）替换为中文名（如3筒、7万、9条、东）。"""
    return re.sub(r'[1-9][mpsz]', lambda m: TILE_NAME_MAP.get(m.group(), m.group()), text)


class TileSelectionDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 160)

        layout = QFormLayout(self)
        self._suit_combo = QComboBox()
        for code, label in SUIT_OPTIONS:
            self._suit_combo.addItem(label, code)
        self._suit_combo.currentIndexChanged.connect(self._reload_values)
        layout.addRow("牌类型", self._suit_combo)

        self._value_combo = QComboBox()
        layout.addRow("具体牌", self._value_combo)
        self._reload_values()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _reload_values(self) -> None:
        suit = str(self._suit_combo.currentData())
        self._value_combo.clear()
        if suit == "z":
            for tile_id, label in HONOR_OPTIONS:
                self._value_combo.addItem(f"{label} ({tile_id})", tile_id)
            return
        suit_name = dict(SUIT_OPTIONS).get(suit, suit)
        for value in range(1, 10):
            tile_id = f"{value}{suit}"
            self._value_combo.addItem(f"{value}{suit_name} ({tile_id})", tile_id)

    def selected_tile(self) -> str:
        return str(self._value_combo.currentData())


class MeldSelectionDialog(QDialog):
    def __init__(self, title: str, parent=None, existing_meld=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 300)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._type_combo = QComboBox()
        for meld_type, label in MELD_TYPE_OPTIONS:
            self._type_combo.addItem(label, meld_type)
        self._type_combo.currentIndexChanged.connect(self._sync_tile_rows)
        form.addRow("副露类型", self._type_combo)
        layout.addLayout(form)

        self._tile_rows: list[tuple[QComboBox, QComboBox]] = []
        tile_grid = QGridLayout()
        tile_grid.addWidget(QLabel("序号"), 0, 0)
        tile_grid.addWidget(QLabel("牌类型"), 0, 1)
        tile_grid.addWidget(QLabel("具体牌"), 0, 2)
        for idx in range(4):
            tile_grid.addWidget(QLabel(f"牌{idx + 1}"), idx + 1, 0)
            suit_combo = QComboBox()
            for code, label in SUIT_OPTIONS:
                suit_combo.addItem(label, code)
            value_combo = QComboBox()
            suit_combo.currentIndexChanged.connect(
                lambda _=None, sc=suit_combo, vc=value_combo: self._reload_value_combo(sc, vc)
            )
            self._reload_value_combo(suit_combo, value_combo)
            tile_grid.addWidget(suit_combo, idx + 1, 1)
            tile_grid.addWidget(value_combo, idx + 1, 2)
            self._tile_rows.append((suit_combo, value_combo))
        layout.addLayout(tile_grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_tile_rows()

        if existing_meld is not None:
            type_idx = self._type_combo.findData(existing_meld.meld_type)
            if type_idx >= 0:
                self._type_combo.setCurrentIndex(type_idx)
                self._sync_tile_rows()
            for i, tile in enumerate(existing_meld.tiles[:4]):
                if not getattr(tile, "tile_id", None):
                    continue
                suit = tile.tile_id[-1]
                suit_combo, value_combo = self._tile_rows[i]
                suit_idx = suit_combo.findData(suit)
                if suit_idx >= 0:
                    suit_combo.blockSignals(True)
                    suit_combo.setCurrentIndex(suit_idx)
                    suit_combo.blockSignals(False)
                    self._reload_value_combo(suit_combo, value_combo)
                val_idx = value_combo.findData(tile.tile_id)
                if val_idx >= 0:
                    value_combo.setCurrentIndex(val_idx)

    def _reload_value_combo(self, suit_combo: QComboBox, value_combo: QComboBox) -> None:
        suit = str(suit_combo.currentData())
        value_combo.clear()
        if suit == "z":
            for tile_id, label in HONOR_OPTIONS:
                value_combo.addItem(f"{label} ({tile_id})", tile_id)
            return
        suit_name = dict(SUIT_OPTIONS).get(suit, suit)
        for value in range(1, 10):
            tile_id = f"{value}{suit}"
            value_combo.addItem(f"{value}{suit_name} ({tile_id})", tile_id)

    def _sync_tile_rows(self) -> None:
        meld_type = str(self._type_combo.currentData())
        enabled_count = 4 if meld_type.startswith("kan") else 3
        for idx, (suit_combo, value_combo) in enumerate(self._tile_rows):
            enabled = idx < enabled_count
            suit_combo.setEnabled(enabled)
            value_combo.setEnabled(enabled)

    def selected_meld(self) -> MeldGroup:
        meld_type = str(self._type_combo.currentData())
        enabled_count = 4 if meld_type.startswith("kan") else 3
        tile_ids = [str(self._tile_rows[idx][1].currentData()) for idx in range(enabled_count)]
        return meld_from_ids(meld_type, tile_ids)


class ApiConfigDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.resize(660, 560)
        self._config = deepcopy(config)

        deepseek_cfg = self._config.setdefault("deepseek", {})
        vision_cfg = self._config.setdefault("vision", {})
        volc_cfg = vision_cfg.setdefault("volc", {})
        qwen_cfg = vision_cfg.setdefault("qwen", {})
        glm_cfg = vision_cfg.setdefault("glm", {})
        battle_cfg = self._config.setdefault("battle", {})

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ── Tab 1: API 设置 ──────────────────────────────────────────────
        api_tab = QWidget()
        api_layout = QVBoxLayout(api_tab)
        form = QFormLayout()

        self._deepseek_key = QLineEdit(deepseek_cfg.get("api_key", ""))
        self._deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("DeepSeek API Key", self._deepseek_key)

        self._deepseek_model = QLineEdit(deepseek_cfg.get("model", "deepseek-chat"))
        form.addRow("DeepSeek 模型", self._deepseek_model)

        self._vision_provider = QComboBox()
        self._vision_provider.addItem("智能选择（火山优先）", "auto")
        self._vision_provider.addItem("火山方舟 Doubao", "volc")
        self._vision_provider.addItem("阿里百炼 Qwen", "qwen")
        self._vision_provider.addItem("智谱 GLM", "glm")
        provider = vision_cfg.get("provider", "auto")
        self._vision_provider.setCurrentIndex(max(0, self._vision_provider.findData(provider)))
        form.addRow("默认视觉提供方", self._vision_provider)

        self._volc_key = QLineEdit(volc_cfg.get("api_key", ""))
        self._volc_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("火山 API Key", self._volc_key)

        self._volc_model = QLineEdit(volc_cfg.get("model", ""))
        self._volc_model.setPlaceholderText("填写火山推理接入点 ID，例如 ep-2026xxxxxxxx")
        form.addRow("火山接入点 ID", self._volc_model)

        self._volc_endpoint = QLineEdit(
            volc_cfg.get("endpoint", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        )
        form.addRow("火山 API 地址", self._volc_endpoint)

        self._qwen_key = QLineEdit(qwen_cfg.get("api_key", ""))
        self._qwen_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Qwen API Key", self._qwen_key)

        self._qwen_model = QComboBox()
        self._qwen_model.setEditable(True)
        current_qwen_model = qwen_cfg.get("model", "qwen-vl-plus-latest")
        models = list(QWEN_VISION_MODELS)
        if current_qwen_model not in models:
            models.insert(0, current_qwen_model)
        self._qwen_model.addItems(models)
        self._qwen_model.setCurrentText(current_qwen_model)
        form.addRow("Qwen 模型", self._qwen_model)

        self._glm_key = QLineEdit(glm_cfg.get("api_key", ""))
        self._glm_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("GLM API Key", self._glm_key)

        self._glm_model = QLineEdit(glm_cfg.get("model", "glm-4.6v-flash"))
        form.addRow("GLM 模型", self._glm_model)

        self._ai_recognition_enabled = QCheckBox("默认开启 AI 识别")
        self._ai_recognition_enabled.setChecked(bool(battle_cfg.get("ai_recognition_enabled", False)))
        form.addRow("识别开关", self._ai_recognition_enabled)
        api_layout.addLayout(form)

        link_box = QGroupBox("控制台快捷入口")
        link_layout = QHBoxLayout(link_box)
        for key in ("deepseek", "volc", "qwen", "glm"):
            label, url = CONSOLE_LINKS[key]
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=None, target=url: self._open_url(target))
            link_layout.addWidget(btn)
        link_layout.addStretch()
        api_layout.addWidget(link_box)
        api_layout.addStretch()
        tabs.addTab(api_tab, "API 设置")

        # ── Tab 2: 提示词 ────────────────────────────────────────────────
        prompt_scroll = QScrollArea()
        prompt_scroll.setWidgetResizable(True)
        prompt_inner = QWidget()
        prompt_layout = QVBoxLayout(prompt_inner)
        prompt_layout.setSpacing(12)

        self._qwen_sys_edit, _ = self._make_prompt_group(
            prompt_layout,
            "Qwen 系统提示词（system prompt）",
            qwen_cfg.get("system_prompt", QWEN_VISION_SYSTEM_PROMPT),
            QWEN_VISION_SYSTEM_PROMPT,
        )
        self._qwen_user_edit, _ = self._make_prompt_group(
            prompt_layout,
            "Qwen 用户提示词模板  |  占位符：{tile_index}  {local_guess}",
            qwen_cfg.get("user_prompt", QWEN_VISION_USER_PROMPT_TEMPLATE),
            QWEN_VISION_USER_PROMPT_TEMPLATE,
        )
        self._volc_prompt_edit, _ = self._make_prompt_group(
            prompt_layout,
            "火山 / GLM 提示词模板  |  占位符：{tile_index}  {local_guess}",
            vision_cfg.get("volc_prompt", VOLC_VISION_PROMPT_TEMPLATE),
            VOLC_VISION_PROMPT_TEMPLATE,
        )
        prompt_layout.addStretch()
        prompt_scroll.setWidget(prompt_inner)
        tabs.addTab(prompt_scroll, "提示词")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _make_prompt_group(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        current_value: str,
        default_value: str,
    ) -> tuple[QPlainTextEdit, QPushButton]:
        box = QGroupBox(title)
        box_layout = QVBoxLayout(box)
        editor = QPlainTextEdit(current_value)
        editor.setFixedHeight(110)
        box_layout.addWidget(editor)
        reset_btn = QPushButton("恢复默认")
        reset_btn.setMaximumWidth(100)
        reset_btn.clicked.connect(lambda: editor.setPlainText(default_value))
        box_layout.addWidget(reset_btn)
        parent_layout.addWidget(box)
        return editor, reset_btn

    def _open_url(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "打开失败", f"无法打开链接：{url}")

    def updated_config(self) -> dict:
        config = deepcopy(self._config)
        config.setdefault("deepseek", {})
        config.setdefault("vision", {})
        config["vision"].setdefault("volc", {})
        config["vision"].setdefault("qwen", {})
        config["vision"].setdefault("glm", {})
        config.setdefault("battle", {})

        config["deepseek"]["api_key"] = self._deepseek_key.text().strip()
        config["deepseek"]["model"] = self._deepseek_model.text().strip() or "deepseek-chat"
        config["vision"]["provider"] = str(self._vision_provider.currentData())
        config["vision"]["volc"]["api_key"] = self._volc_key.text().strip()
        config["vision"]["volc"]["model"] = self._volc_model.text().strip()
        config["vision"]["volc"]["endpoint"] = (
            self._volc_endpoint.text().strip() or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        )
        config["vision"]["qwen"]["api_key"] = self._qwen_key.text().strip()
        config["vision"]["qwen"]["model"] = self._qwen_model.currentText().strip() or "qwen-vl-plus-latest"
        config["vision"]["glm"]["api_key"] = self._glm_key.text().strip()
        config["vision"]["glm"]["model"] = self._glm_model.text().strip() or "glm-4.6v-flash"
        config["battle"]["ai_recognition_enabled"] = self._ai_recognition_enabled.isChecked()

        # 提示词：空白时移除 key（使用代码默认值）
        qwen_sys = self._qwen_sys_edit.toPlainText().strip()
        if qwen_sys and qwen_sys != QWEN_VISION_SYSTEM_PROMPT:
            config["vision"]["qwen"]["system_prompt"] = qwen_sys
        else:
            config["vision"]["qwen"].pop("system_prompt", None)

        qwen_user = self._qwen_user_edit.toPlainText().strip()
        if qwen_user and qwen_user != QWEN_VISION_USER_PROMPT_TEMPLATE:
            config["vision"]["qwen"]["user_prompt"] = qwen_user
        else:
            config["vision"]["qwen"].pop("user_prompt", None)

        volc_prompt = self._volc_prompt_edit.toPlainText().strip()
        if volc_prompt and volc_prompt != VOLC_VISION_PROMPT_TEMPLATE:
            config["vision"]["volc_prompt"] = volc_prompt
        else:
            config["vision"].pop("volc_prompt", None)

        return config


SUIT_LABEL_MAP = {"m": "万", "p": "筒", "s": "条", "z": "字"}
SUIT_TILES = {
    "m": [f"{i}m" for i in range(1, 10)],
    "p": [f"{i}p" for i in range(1, 10)],
    "s": [f"{i}s" for i in range(1, 10)],
    "z": [f"{i}z" for i in range(1, 8)],
}


class _TileCorrectDialog(QDialog):
    """两级下拉纠错对话框：先选牌型，再选具体牌。"""

    def __init__(self, current_tile_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("纠正牌型")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(240, 120)
        self._result_tile_id: str | None = None

        layout = QVBoxLayout(self)
        row = QHBoxLayout()

        self._suit_combo = QComboBox()
        for suit, label in SUIT_LABEL_MAP.items():
            self._suit_combo.addItem(label, suit)
        # pre-select current suit
        if current_tile_id and len(current_tile_id) >= 2:
            suit = current_tile_id[-1]
            idx = self._suit_combo.findData(suit)
            if idx >= 0:
                self._suit_combo.setCurrentIndex(idx)

        self._tile_combo = QComboBox()
        self._populate_tile_combo()
        # pre-select current tile
        if current_tile_id:
            idx = self._tile_combo.findData(current_tile_id)
            if idx >= 0:
                self._tile_combo.setCurrentIndex(idx)

        self._suit_combo.currentIndexChanged.connect(self._populate_tile_combo)
        row.addWidget(self._suit_combo)
        row.addWidget(self._tile_combo)
        layout.addLayout(row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _populate_tile_combo(self):
        suit = self._suit_combo.currentData() or "m"
        self._tile_combo.clear()
        for tid in SUIT_TILES[suit]:
            self._tile_combo.addItem(TILE_NAME_MAP.get(tid, tid), tid)

    def _on_ok(self):
        self._result_tile_id = self._tile_combo.currentData()
        self.accept()

    @property
    def selected_tile_id(self) -> str | None:
        return self._result_tile_id


class AnalysisPanel(QGroupBox):
    """展示每次 AI 分析的候选牌评分表格。"""

    COLS = ["出牌", "听后", "进张", "危险", "潜番", "综合", "MC%"]

    def __init__(self) -> None:
        super().__init__("候选分析")
        self._header = QLabel("向听数：-- | 策略：--")
        self._header.setStyleSheet(f"font-size:12px; color:{_C_2ND}; padding:2px 0;")
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(self.COLS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setMinimumHeight(140)
        self._table.setAlternatingRowColors(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._header)
        layout.addWidget(self._table)

    def refresh(self, analysis: dict, recommended: str) -> None:
        shanten = analysis.get("shanten", "--")
        mode_map = {"attack": "攻牌", "defense": "守牌", "balance": "平衡"}
        mode_raw = analysis.get("strategy_mode", "--")
        mode = mode_map.get(mode_raw, mode_raw)
        self._header.setText(f"向听数：{shanten} | 策略：{mode}")
        candidates = analysis.get("candidates", [])
        self._table.setRowCount(len(candidates))
        for row, c in enumerate(candidates):
            mc = c.get("mc") or {}
            mc_win = mc.get("win_rate")
            mc_text = f"{mc_win:.1%}" if mc_win is not None else "--"
            discard_id = c.get("discard", "")
            values = [
                TILE_NAME_MAP.get(discard_id, discard_id),
                str(c.get("shanten_after", "--")),
                str(c.get("ukeire_count", "--")),
                c.get("danger_level", "--"),
                str(c.get("potential_fan", "--")),
                f"{c.get('score', 0):.1f}",
                mc_text,
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, col, item)
            if c.get("discard") == recommended and recommended:
                for col in range(7):
                    cell = self._table.item(row, col)
                    if cell:
                        cell.setBackground(QColor("#1e3828"))


class BattlePanel(QWidget):
    start_requested = pyqtSignal()
    end_requested = pyqtSignal()
    state_changed = pyqtSignal(object)
    analysis_requested = pyqtSignal(str)
    recognition_only_requested = pyqtSignal(str)   # 我方编辑：识别+本地分析，不触发DeepSeek
    state_reanalyze_requested = pyqtSignal(str)    # 敌方编辑：不识别，仅重算本地分析
    reanalyze_with_ai_requested = pyqtSignal(str)  # 重试：不识别，重跑本地+AI
    config_requested = pyqtSignal()
    config_save_requested = pyqtSignal(dict)        # 请求主窗口保存 config 到磁盘（携带需更新的 key→value）
    _global_key_pressed = pyqtSignal(str)           # 全局键盘钩子 → 主线程（内部使用）
    tile_correction_requested = pyqtSignal(int, str)   # (tile_index, correct_tile_id)
    meld_correction_requested = pyqtSignal(int, str)   # (flat_meld_tile_index, correct_tile_id)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = deepcopy(config)
        self._state = BattleState(
            ai_recognition_enabled=bool(self._config.get("battle", {}).get("ai_recognition_enabled", False)),
            vision_provider=self._config.get("vision", {}).get("provider", "auto"),
        )
        self._stream_buffer = ""
        self._stream_discard_found = False
        self._shortcut_suit = "m"
        self._shortcut_selected: int | None = None
        self._suit_btns: dict[str, QPushButton] = {}
        self._tile_strip_btns: list[QPushButton] = []
        _default_shortcut_keys = {
            "万": "W", "筒": "T", "条": "B", "字": "Z",
            "添加": "Return", "撤销": "U", "清空": "C", "分析": "A", "切换回合": "Q",
        }
        saved = self._config.get("shortcut_keys", {})
        self._shortcut_keys = {**_default_shortcut_keys, **saved}
        self._active_shortcuts: list = []
        self._global_kb_hook = None
        self._global_actions: dict = {}
        self._global_key_pressed.connect(self._on_global_key)
        self._setup_ui()
        self._rebuild_shortcuts()
        self._render_state()
        self.clear_round_feedback()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._ai_checkbox = QCheckBox("开启AI识别")
        self._ai_checkbox.setChecked(self._state.ai_recognition_enabled)
        self._ai_checkbox.toggled.connect(self._on_ai_toggle)
        top.addWidget(self._ai_checkbox)

        self._game_in_progress = False

        self._start_btn = QPushButton("开始")
        self._start_btn.clicked.connect(self._on_start_clicked)
        top.addWidget(self._start_btn)

        self._end_btn = QPushButton("结束游戏")
        self._end_btn.clicked.connect(self.end_requested.emit)
        self._end_btn.setEnabled(False)
        top.addWidget(self._end_btn)

        self._config_btn = QPushButton("API 设置")
        self._config_btn.clicked.connect(self.config_requested.emit)
        top.addWidget(self._config_btn)

        self._busy_label = QLabel("空闲")
        top.addWidget(self._busy_label)
        top.addStretch()
        root.addLayout(top)

        content = QHBoxLayout()
        root.addLayout(content, 1)

        left_widget = QWidget()
        left_widget.setMaximumWidth(290)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self._build_player_group("敌方牌区", enemy=True))
        left.addWidget(self._build_player_group("我方牌区", enemy=False))
        content.addWidget(left_widget)

        center_box = self._build_center_group()
        self._train_success_label = QLabel("")
        self._train_success_label.setWordWrap(True)
        self._train_success_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._train_success_label.setStyleSheet(f"color:{_C_2ND}; font-size:12px; padding:4px;")
        self._analysis_panel = AnalysisPanel()
        self._meta_label = QLabel("最近一次分析：--")
        self._meta_label.setWordWrap(True)
        self._meta_label.setStyleSheet(f"color:{_C_MUTED}; font-size:10px; padding: 2px 4px;")
        center = QVBoxLayout()
        center.addWidget(center_box)
        center.addWidget(self._train_success_label)
        center.addStretch()
        center.addWidget(self._meta_label)
        center_widget = QWidget()
        center_widget.setMaximumWidth(370)
        center_widget.setLayout(center)
        content.addWidget(center_widget, 1)

        right = QVBoxLayout()
        right.addWidget(self._build_advice_group(), 3)
        right.addWidget(self._analysis_panel, 2)
        content.addLayout(right, 2)

    def _build_player_group(self, title: str, enemy: bool) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)

        discard_row = QHBoxLayout()
        discard_row.addWidget(QLabel("弃牌区"))
        discard_row.addStretch()
        discard_add = QPushButton("添加")
        discard_add.clicked.connect(lambda: self._add_discard(enemy))
        discard_row.addWidget(discard_add)
        discard_undo = QPushButton("撤销")
        discard_undo.clicked.connect(lambda: self._undo_discard(enemy))
        discard_row.addWidget(discard_undo)
        discard_clear = QPushButton("清空")
        discard_clear.clicked.connect(lambda: self._clear_discards(enemy))
        discard_row.addWidget(discard_clear)
        layout.addLayout(discard_row)

        discard_container = QWidget()
        discard_layout = QGridLayout(discard_container)
        discard_layout.setContentsMargins(0, 0, 0, 0)
        discard_layout.setSpacing(4)
        discard_layout.addWidget(QLabel("（空）"), 0, 0)
        layout.addWidget(discard_container)

        meld_row = QHBoxLayout()
        meld_row.addWidget(QLabel("副露区"))
        meld_row.addStretch()
        meld_add = QPushButton("添加")
        meld_add.clicked.connect(lambda: self._add_meld(enemy))
        meld_row.addWidget(meld_add)
        meld_undo = QPushButton("撤销")
        meld_undo.clicked.connect(lambda: self._undo_meld(enemy))
        meld_row.addWidget(meld_undo)
        meld_clear = QPushButton("清空")
        meld_clear.clicked.connect(lambda: self._clear_melds(enemy))
        meld_row.addWidget(meld_clear)
        layout.addLayout(meld_row)

        meld_container = QWidget()
        meld_layout = QHBoxLayout(meld_container)
        meld_layout.setContentsMargins(0, 0, 0, 0)
        meld_layout.setSpacing(4)
        meld_layout.addWidget(QLabel("（空）"))
        meld_layout.addStretch()
        layout.addWidget(meld_container)

        if enemy:
            self._enemy_discard_layout = discard_layout
            self._enemy_meld_layout = meld_layout
        else:
            self._self_discard_layout = discard_layout
            self._self_meld_layout = meld_layout
        return box

    def _build_center_group(self) -> QGroupBox:
        box = QGroupBox("战斗状态")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        baida_widget = QWidget()
        baida_layout = QHBoxLayout(baida_widget)
        baida_layout.setContentsMargins(0, 0, 0, 0)
        self._baida_suit_combo = QComboBox()
        self._baida_suit_combo.addItem("未设置", "")
        for code, label in SUIT_OPTIONS:
            self._baida_suit_combo.addItem(label, code)
        self._baida_suit_combo.currentIndexChanged.connect(self._on_baida_suit_changed)
        baida_layout.addWidget(self._baida_suit_combo)

        self._baida_value_combo = QComboBox()
        self._baida_value_combo.currentIndexChanged.connect(self._on_baida_changed)
        baida_layout.addWidget(self._baida_value_combo)
        self._reload_baida_values()
        form.addRow("财神", baida_widget)

        self._remaining_spin = QSpinBox()
        self._remaining_spin.setRange(0, 136)
        self._remaining_spin.setValue(self._state.remaining_tiles)
        self._remaining_spin.valueChanged.connect(self._on_remaining_changed)
        form.addRow("剩余张数", self._remaining_spin)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem(PROVIDER_LABELS["auto"], "auto")
        self._provider_combo.addItem(PROVIDER_LABELS["volc"], "volc")
        self._provider_combo.addItem(PROVIDER_LABELS["qwen"], "qwen")
        self._provider_combo.addItem(PROVIDER_LABELS["glm"], "glm")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("视觉模型", self._provider_combo)

        # ---- 庄家 / 门风 / 暗杠（2人模式） ----
        self._dealer_combo = QComboBox()
        self._dealer_combo.addItem("自家", "self")
        self._dealer_combo.addItem("对手", "across")
        self._dealer_combo.currentIndexChanged.connect(self._on_dealer_changed)
        form.addRow("庄家", self._dealer_combo)

        self._wind_combo = QComboBox()
        self._wind_combo.addItem("东 (1z)", "1z")
        self._wind_combo.addItem("南 (2z)", "2z")
        self._wind_combo.currentIndexChanged.connect(self._on_wind_changed)
        form.addRow("门风", self._wind_combo)

        self._kan_closed_combo = QComboBox()
        for i in range(5):
            self._kan_closed_combo.addItem(str(i), i)
        self._kan_closed_combo.currentIndexChanged.connect(self._on_kan_closed_changed)
        form.addRow("暗杠次数", self._kan_closed_combo)

        layout.addLayout(form)

        hand_top = QHBoxLayout()
        self._turn_label = QLabel("我方手牌区")
        hand_top.addWidget(self._turn_label)
        hand_top.addStretch()
        self._recognize_btn = QPushButton("识别")
        self._recognize_btn.clicked.connect(lambda: self.recognition_only_requested.emit("manual_recognize"))
        hand_top.addWidget(self._recognize_btn)
        hand_add = QPushButton("添加")
        hand_add.clicked.connect(self._add_hand_tile)
        hand_top.addWidget(hand_add)
        hand_undo = QPushButton("撤销")
        hand_undo.clicked.connect(self._undo_hand_tile)
        hand_top.addWidget(hand_undo)
        hand_clear = QPushButton("清空")
        hand_clear.clicked.connect(self._clear_hand_tiles)
        hand_top.addWidget(hand_clear)
        layout.addLayout(hand_top)

        self._hand_tiles_container = QWidget()
        self._hand_tiles_layout = QGridLayout(self._hand_tiles_container)
        self._hand_tiles_layout.setContentsMargins(0, 0, 0, 0)
        self._hand_tiles_layout.setSpacing(4)
        layout.addWidget(self._hand_tiles_container)

        self._recognition_label = QLabel("识别来源：manual")
        layout.addWidget(self._recognition_label)

        self._build_shortcut_group(layout)
        return box

    def _build_advice_group(self) -> QGroupBox:
        box = QGroupBox("AI 建议")
        layout = QVBoxLayout(box)

        # AI 分析开关 + 模型选择
        ai_row = QHBoxLayout()
        self._deepseek_checkbox = QCheckBox("开启 AI 分析")
        self._deepseek_checkbox.setChecked(self._state.deepseek_enabled)
        self._deepseek_checkbox.toggled.connect(self._on_deepseek_toggle)
        ai_row.addWidget(self._deepseek_checkbox)
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItem("DeepSeek", "deepseek")
        self._ai_provider_combo.addItem("千问", "qianwen")
        _provider_idx = 1 if getattr(self._state, "ai_provider", "deepseek") == "qianwen" else 0
        self._ai_provider_combo.setCurrentIndex(_provider_idx)
        self._ai_provider_combo.setEnabled(self._state.deepseek_enabled)
        self._ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        ai_row.addWidget(self._ai_provider_combo)
        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setPlaceholderText("模型名称")
        self._ai_model_edit.setFixedWidth(120)
        self._ai_model_edit.setEnabled(self._state.deepseek_enabled)
        self._ai_model_edit.setText(self._state.ai_model or self._default_model_for_provider(self._state.ai_provider))
        self._ai_model_edit.editingFinished.connect(self._on_ai_model_changed)
        ai_row.addWidget(self._ai_model_edit)
        ai_row.addStretch()
        layout.addLayout(ai_row)

        self._recommended_label = QLabel("当前推荐出牌：--")
        self._recommended_label.setWordWrap(True)
        layout.addWidget(self._recommended_label)

        self._strategy_label = QLabel("策略类型：--")
        self._strategy_label.setWordWrap(True)
        layout.addWidget(self._strategy_label)

        self._state_summary_label = QLabel("当前牌局摘要：--")
        self._state_summary_label.setWordWrap(True)
        layout.addWidget(self._state_summary_label)

        self._summary_edit = QTextEdit()
        self._summary_edit.setReadOnly(True)
        self._summary_edit.setMinimumHeight(100)
        self._summary_edit.setPlaceholderText("推荐理由摘要会显示在这里")
        layout.addWidget(self._summary_edit, 1)

        self._candidate_label = QLabel("候选动作：--")
        self._candidate_label.setWordWrap(True)
        layout.addWidget(self._candidate_label)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(f"color:{_C_ERR};")
        layout.addWidget(self._error_label)

        retry_btn = QPushButton("分析")
        retry_btn.clicked.connect(lambda: self.reanalyze_with_ai_requested.emit("retry"))
        layout.addWidget(retry_btn)

        self._progress_label = QLabel("")
        self._progress_label.setWordWrap(True)
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._progress_label.setStyleSheet(f"color:{_C_AI}; font-size:11px;")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        return box

    def _provider_text(self) -> str:
        provider = self._config.get("vision", {}).get("provider", "auto")
        return PROVIDER_LABELS.get(provider, provider)

    def _on_provider_changed(self) -> None:
        provider = str(self._provider_combo.currentData() or "auto")
        self._config.setdefault("vision", {})["provider"] = provider
        self._state.vision_provider = provider
        self._record_and_emit("set_vision_provider", {"provider": provider})

    def _reload_baida_values(self) -> None:
        suit = str(self._baida_suit_combo.currentData() or "")
        self._baida_value_combo.blockSignals(True)
        self._baida_value_combo.clear()
        if not suit:
            self._baida_value_combo.addItem("未设置", "")
            self._baida_value_combo.setEnabled(False)
        elif suit == "z":
            for tile_id, label in HONOR_OPTIONS:
                self._baida_value_combo.addItem(f"{label} ({tile_id})", tile_id)
            self._baida_value_combo.setEnabled(True)
        else:
            suit_name = dict(SUIT_OPTIONS).get(suit, suit)
            for value in range(1, 10):
                tile_id = f"{value}{suit}"
                self._baida_value_combo.addItem(f"{value}{suit_name} ({tile_id})", tile_id)
            self._baida_value_combo.setEnabled(True)
        self._baida_value_combo.blockSignals(False)

    def _on_baida_suit_changed(self) -> None:
        self._reload_baida_values()
        self._on_baida_changed()

    def _record_and_emit(self, action: str, detail: dict | None = None) -> None:
        self._state.append_operation(action, detail or {})
        self._render_state()
        self.state_changed.emit(self.current_state())

    def _adjust_remaining(self, delta: int) -> None:
        self._state.remaining_tiles = max(0, self._state.remaining_tiles + delta)
        self._remaining_spin.blockSignals(True)
        self._remaining_spin.setValue(self._state.remaining_tiles)
        self._remaining_spin.blockSignals(False)

    def _on_ai_toggle(self, checked: bool) -> None:
        self._state.ai_recognition_enabled = checked
        self._record_and_emit("toggle_ai_recognition", {"enabled": checked})

    def _default_model_for_provider(self, provider: str) -> str:
        cfg = self._config.get(provider, {})
        _fallback = {"deepseek": "deepseek-chat", "qianwen": "qwen-turbo-latest"}
        return cfg.get("model", _fallback.get(provider, "")) or _fallback.get(provider, "")

    def _on_deepseek_toggle(self, checked: bool) -> None:
        self._state.deepseek_enabled = checked
        self._ai_provider_combo.setEnabled(checked)
        self._ai_model_edit.setEnabled(checked)
        self._record_and_emit("toggle_deepseek", {"enabled": checked})

    def _on_ai_provider_changed(self, index: int) -> None:
        provider = str(self._ai_provider_combo.itemData(index) or "deepseek")
        self._state.ai_provider = provider
        # 切换 provider 时自动填入该 provider 的默认模型
        self._state.ai_model = self._default_model_for_provider(provider)
        self._ai_model_edit.blockSignals(True)
        self._ai_model_edit.setText(self._state.ai_model)
        self._ai_model_edit.blockSignals(False)
        self._record_and_emit("change_ai_provider", {"provider": provider, "model": self._state.ai_model})

    def _on_ai_model_changed(self) -> None:
        model = self._ai_model_edit.text().strip()
        if not model:
            model = self._default_model_for_provider(self._state.ai_provider)
            self._ai_model_edit.setText(model)
        self._state.ai_model = model
        self._record_and_emit("change_ai_model", {"model": model})

    def _on_start_clicked(self) -> None:
        self._state.append_operation("start_analysis", {"trigger": "start"})
        self.start_requested.emit()
        self.state_changed.emit(self.current_state())
        self.analysis_requested.emit("start")

    def _on_baida_changed(self) -> None:
        self._state.baida_tile = str(self._baida_value_combo.currentData() or "")
        self._record_and_emit("set_baida_tile", {"tile": self._state.baida_tile})

    def _on_dealer_changed(self) -> None:
        self._state.dealer_seat = str(self._dealer_combo.currentData() or "self")
        self._record_and_emit("set_dealer", {"dealer_seat": self._state.dealer_seat})

    def _on_wind_changed(self) -> None:
        self._state.self_wind = str(self._wind_combo.currentData() or "1z")
        self._record_and_emit("set_wind", {"self_wind": self._state.self_wind})

    def _on_kan_closed_changed(self) -> None:
        self._state.kan_closed_count = int(self._kan_closed_combo.currentData() or 0)
        self._record_and_emit("set_kan_closed", {"kan_closed_count": self._state.kan_closed_count})

    def _on_remaining_changed(self, value: int) -> None:
        self._state.remaining_tiles = int(value)
        self._record_and_emit("set_remaining_tiles", {"remaining_tiles": int(value)})

    def _add_hand_tile(self) -> None:
        dialog = TileSelectionDialog("添加我方手牌", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        tile_id = dialog.selected_tile()
        self._state.self_hand.append(tile_from_id(tile_id))
        self._record_and_emit("add_self_hand", {"tile": tile_id})

    def _undo_hand_tile(self) -> None:
        if not self._state.self_hand:
            return
        tile = self._state.self_hand.pop()
        self._record_and_emit("undo_self_hand", {"tile": tile.tile_id})

    def _clear_hand_tiles(self) -> None:
        if not self._state.self_hand:
            return
        count = len(self._state.self_hand)
        self._state.self_hand.clear()
        self._record_and_emit("clear_self_hand", {"count": count})

    def _add_discard(self, enemy: bool, tile_id: str | None = None) -> None:
        if tile_id is None:
            dialog = TileSelectionDialog("添加弃牌", self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            tile_id = dialog.selected_tile()
        self._adjust_remaining(-1)
        if enemy:
            self._state.enemy_discards.append(tile_from_id(tile_id))
            self._record_and_emit("add_enemy_discard", {"tile": tile_id})
        else:
            self._state.self_discards.append(tile_from_id(tile_id))
            self._record_and_emit("add_self_discard", {"tile": tile_id})
        self._state.current_turn = "self" if enemy else "enemy"
        self._update_turn_label()
        self._update_shortcut_status()
        if enemy:
            self.recognition_only_requested.emit("manual_recognize")

    def _undo_discard(self, enemy: bool) -> None:
        discards = self._state.enemy_discards if enemy else self._state.self_discards
        if not discards:
            return
        tile = discards.pop()
        self._adjust_remaining(+1)
        if enemy:
            self._record_and_emit("undo_enemy_discard", {"tile": tile.tile_id})
            self.state_reanalyze_requested.emit("enemy_discard_undo")
        else:
            self._record_and_emit("undo_self_discard", {"tile": tile.tile_id})
            self.recognition_only_requested.emit("self_discard_undo")

    def _clear_discards(self, enemy: bool) -> None:
        discards = self._state.enemy_discards if enemy else self._state.self_discards
        if not discards:
            return
        count = len(discards)
        discards.clear()
        self._adjust_remaining(count)
        if enemy:
            self._record_and_emit("clear_enemy_discards", {"count": count})
            self.state_reanalyze_requested.emit("enemy_discard_clear")
        else:
            self._record_and_emit("clear_self_discards", {"count": count})
            self.recognition_only_requested.emit("self_discard_clear")

    @staticmethod
    def _is_kan(meld_type: str) -> bool:
        return "kan" in meld_type

    def _add_meld(self, enemy: bool) -> None:
        dialog = MeldSelectionDialog("添加副露", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        meld = dialog.selected_meld()
        if self._is_kan(meld.meld_type):
            self._adjust_remaining(-1)
        if enemy:
            self._state.enemy_melds.append(meld)
            self._record_and_emit("add_enemy_meld", {"meld_type": meld.meld_type, "tiles": [tile.tile_id for tile in meld.tiles]})
        else:
            self._state.self_melds.append(meld)
            self._state.self_melds_locked = True
            self._record_and_emit("add_self_meld", {"meld_type": meld.meld_type, "tiles": [tile.tile_id for tile in meld.tiles]})

    def _undo_meld(self, enemy: bool) -> None:
        melds = self._state.enemy_melds if enemy else self._state.self_melds
        if not melds:
            return
        meld = melds.pop()
        if self._is_kan(meld.meld_type):
            self._adjust_remaining(+1)
        if enemy:
            self._record_and_emit("undo_enemy_meld", {"meld_type": meld.meld_type, "tiles": [tile.tile_id for tile in meld.tiles]})
            self.state_reanalyze_requested.emit("enemy_meld_undo")
        else:
            self._state.self_melds_locked = True
            self._record_and_emit("undo_self_meld", {"meld_type": meld.meld_type, "tiles": [tile.tile_id for tile in meld.tiles]})
            self.recognition_only_requested.emit("self_meld_undo")

    def _clear_melds(self, enemy: bool) -> None:
        melds = self._state.enemy_melds if enemy else self._state.self_melds
        if not melds:
            return
        count = len(melds)
        kan_count = sum(1 for m in melds if self._is_kan(m.meld_type))
        melds.clear()
        if kan_count:
            self._adjust_remaining(kan_count)
        if enemy:
            self._record_and_emit("clear_enemy_melds", {"count": count})
            self.state_reanalyze_requested.emit("enemy_meld_clear")
        else:
            self._state.self_melds_locked = False
            self._record_and_emit("clear_self_melds", {"count": count})
            self.recognition_only_requested.emit("self_meld_clear")

    _HAND_COLS = 8     # tiles per row before wrapping
    _DISCARD_COLS = 6  # discard tiles per row before wrapping

    def _rebuild_discard_buttons(self, discards, is_enemy: bool, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not discards:
            layout.addWidget(QLabel("（空）"), 0, 0)
            return
        col, row = 0, 0
        for idx, tile in enumerate(discards):
            if not tile.tile_id:
                continue
            btn = QPushButton(tile_display(tile.tile_id))
            btn.setFixedWidth(52)
            btn.setToolTip("点击删除")
            btn.clicked.connect(
                lambda _checked, i=idx, e=is_enemy: self._on_discard_tile_click(i, e)
            )
            layout.addWidget(btn, row, col)
            col += 1
            if col >= self._DISCARD_COLS:
                col = 0
                row += 1

    def _on_discard_tile_click(self, tile_index: int, is_enemy: bool) -> None:
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        delete_act = menu.addAction("删除")
        chosen = menu.exec(QCursor.pos())
        if chosen == delete_act:
            discards = self._state.enemy_discards if is_enemy else self._state.self_discards
            if tile_index < len(discards):
                tile = discards.pop(tile_index)
                self._adjust_remaining(+1)
                key = "delete_enemy_discard" if is_enemy else "delete_self_discard"
                self._record_and_emit(key, {"index": tile_index, "tile": tile.tile_id})
                lo = self._enemy_discard_layout if is_enemy else self._self_discard_layout
                self._rebuild_discard_buttons(discards, is_enemy, lo)

    def _rebuild_hand_tile_buttons(self, tiles) -> None:
        layout = self._hand_tiles_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tiles:
            layout.addWidget(QLabel("（空）"), 0, 0)
            return

        col = 0
        row = 0
        for idx, tile in enumerate(tiles):
            if not tile.tile_id:
                continue
            conf = float(getattr(tile, "confidence", 1.0) or 1.0)
            label = tile_display(tile.tile_id)
            btn = QPushButton(label)
            btn.setFixedWidth(52)
            btn.setToolTip(f"置信度: {conf:.0%}  点击操作")
            if conf < 0.9:
                btn.setStyleSheet(f"color: {_C_ERR}; font-weight: bold;")
            else:
                btn.setStyleSheet(f"color: {_C_TEXT};")
            btn.clicked.connect(
                lambda _checked, i=idx, t=tile.tile_id: self._on_hand_tile_btn_click(i, t)
            )
            layout.addWidget(btn, row, col)
            col += 1
            if col >= self._HAND_COLS:
                col = 0
                row += 1

    def _on_hand_tile_btn_click(self, tile_index: int, tile_id: str) -> None:
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        correct_act = menu.addAction("纠正")
        delete_act = menu.addAction("删除")
        chosen = menu.exec(QCursor.pos())
        if chosen == correct_act:
            self._on_tile_correction_click(tile_index, tile_id)
        elif chosen == delete_act:
            self._delete_hand_tile_at(tile_index)

    def _delete_hand_tile_at(self, tile_index: int) -> None:
        if tile_index < len(self._state.self_hand):
            tile = self._state.self_hand.pop(tile_index)
            self._rebuild_hand_tile_buttons(self._state.self_hand)
            self._record_and_emit("delete_self_hand", {"index": tile_index, "tile": tile.tile_id})

    def _on_tile_correction_click(self, tile_index: int, current_tile_id: str) -> None:
        dlg = _TileCorrectDialog(current_tile_id, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        correct_id = dlg.selected_tile_id
        if not correct_id:
            return
        # Always update confidence=1.0 and emit training signal (even if tile unchanged,
        # confirming a correct recognition reinforces the sample).
        if tile_index < len(self._state.self_hand):
            self._state.self_hand[tile_index] = tile_from_id(correct_id)
            self._rebuild_hand_tile_buttons(self._state.self_hand)
            self._record_and_emit("correct_tile", {"index": tile_index, "tile": correct_id})
        self.tile_correction_requested.emit(tile_index, correct_id)

    # ─── 回合指示器 ──────────────────────────────────────────────

    def _update_turn_label(self) -> None:
        turn = self._state.current_turn
        if turn == "self":
            self._turn_label.setText("我方手牌区  ● 我方回合")
            self._turn_label.setStyleSheet(f"color: {_C_SELF}; font-weight: bold;")
        elif turn == "enemy":
            self._turn_label.setText("我方手牌区  ● 敌方回合")
            self._turn_label.setStyleSheet(f"color: {_C_ENEMY}; font-weight: bold;")
        else:
            self._turn_label.setText("我方手牌区")
            self._turn_label.setStyleSheet("")

    # ─── 快捷键操作模块 ──────────────────────────────────────────

    def _build_shortcut_group(self, layout) -> None:
        from PyQt6.QtWidgets import QGroupBox
        box = QGroupBox("快捷键操作")
        vbox = QVBoxLayout(box)

        # 牌型切换行
        suit_row = QHBoxLayout()
        suit_row.addWidget(QLabel("牌型:"))
        suit_map = [("m", "万"), ("p", "筒"), ("s", "条"), ("z", "字")]
        for suit_code, suit_name in suit_map:
            key = self._shortcut_keys.get(suit_name, "")
            btn = QPushButton(f"{key}={suit_name}")
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda _=None, c=suit_code: self._switch_shortcut_suit(c))
            self._suit_btns[suit_code] = btn
            suit_row.addWidget(btn)
        suit_row.addStretch()
        config_btn = QPushButton("配置")
        config_btn.setFixedWidth(50)
        config_btn.clicked.connect(self._open_shortcut_config)
        suit_row.addWidget(config_btn)
        vbox.addLayout(suit_row)

        # 红框牌条
        self._tile_strip_container = QWidget()
        self._tile_strip_container.setStyleSheet(
            f"QWidget {{ border: 2px solid {_C_ENEMY}; border-radius: 4px; padding: 2px; }}"
        )
        self._tile_strip_layout = QHBoxLayout(self._tile_strip_container)
        self._tile_strip_layout.setContentsMargins(4, 2, 4, 2)
        self._tile_strip_layout.setSpacing(3)
        vbox.addWidget(self._tile_strip_container)

        # 快捷键说明行
        add_key = self._shortcut_keys.get("添加", "Return")
        undo_key = self._shortcut_keys.get("撤销", "U")
        clear_key = self._shortcut_keys.get("清空", "C")
        analyze_key = self._shortcut_keys.get("分析", "A")
        toggle_key = self._shortcut_keys.get("切换回合", "Q")
        self._shortcut_hint_label = QLabel(
            f"添加:{add_key}  撤销:{undo_key}  清空:{clear_key}  分析:{analyze_key}  切换回合:{toggle_key}  (数字键1-9选牌)"
        )
        self._shortcut_hint_label.setStyleSheet(f"color: {_C_MUTED}; font-size: 11px;")
        vbox.addWidget(self._shortcut_hint_label)

        # 状态标签
        self._shortcut_status_label = QLabel("请先添加弃牌以自动切换回合")
        self._shortcut_status_label.setStyleSheet(f"color: {_C_MUTED}; font-size: 11px;")
        vbox.addWidget(self._shortcut_status_label)

        layout.addWidget(box)
        self._rebuild_tile_strip()
        self._update_suit_btn_highlight()

    def _switch_shortcut_suit(self, suit: str) -> None:
        self._shortcut_suit = suit
        self._shortcut_selected = None
        self._rebuild_tile_strip()
        self._update_suit_btn_highlight()

    def _update_suit_btn_highlight(self) -> None:
        for code, btn in self._suit_btns.items():
            if code == self._shortcut_suit:
                btn.setStyleSheet(f"background: {_C_SELF}; color: #1a2418; font-weight: bold;")
            else:
                btn.setStyleSheet("")

    def _rebuild_tile_strip(self) -> None:
        while self._tile_strip_layout.count():
            item = self._tile_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tile_strip_btns.clear()

        suit = self._shortcut_suit
        if suit == "z":
            tiles = [(i + 1, tid) for i, tid in enumerate(
                ["1z", "2z", "3z", "4z", "5z", "6z", "7z"]
            )]
        else:
            tiles = [(n, f"{n}{suit}") for n in range(1, 10)]

        for number, tile_id in tiles:
            label = TILE_NAME_MAP.get(tile_id, tile_id)
            btn = QPushButton(label)
            btn.setFixedWidth(40)
            btn.clicked.connect(lambda _=None, n=number: self._shortcut_select(n))
            self._tile_strip_btns.append(btn)
            self._tile_strip_layout.addWidget(btn)
        self._tile_strip_layout.addStretch()

    def _shortcut_select(self, number: int) -> None:
        self._shortcut_selected = number
        for i, btn in enumerate(self._tile_strip_btns):
            if i + 1 == number:
                btn.setStyleSheet(f"background: {_C_GOLD}; color: #1a2418; font-weight: bold;")
            else:
                btn.setStyleSheet("")

    def _shortcut_add(self) -> None:
        if self._shortcut_selected is None:
            return
        suit = self._shortcut_suit
        if suit == "z":
            tile_id = f"{self._shortcut_selected}z"
        else:
            tile_id = f"{self._shortcut_selected}{suit}"
        turn = self._state.current_turn
        if turn == "none":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "请先通过弃牌区【添加】按钮切换回合")
            return
        enemy = (turn == "enemy")
        # 清除选中高亮
        for btn in self._tile_strip_btns:
            btn.setStyleSheet("")
        self._shortcut_selected = None
        self._add_discard(enemy=enemy, tile_id=tile_id)

    def _shortcut_undo(self) -> None:
        turn = self._state.current_turn
        if turn == "none":
            return
        enemy = (turn == "enemy")
        self._undo_discard(enemy)

    def _shortcut_clear(self) -> None:
        turn = self._state.current_turn
        if turn == "none":
            return
        enemy = (turn == "enemy")
        self._clear_discards(enemy)

    def _shortcut_toggle_turn(self) -> None:
        if self._state.current_turn == "enemy":
            self._state.current_turn = "self"
        else:
            self._state.current_turn = "enemy"
        self._update_turn_label()
        self._update_shortcut_status()
        if self._state.current_turn == "self":
            self.recognition_only_requested.emit("manual_recognize")

    def _update_shortcut_status(self) -> None:
        if not hasattr(self, "_shortcut_status_label"):
            return
        turn = self._state.current_turn
        if turn == "self":
            self._shortcut_status_label.setText("将添加到：我方弃牌区")
            self._shortcut_status_label.setStyleSheet(f"color: {_C_SELF}; font-size: 11px; font-weight: bold;")
        elif turn == "enemy":
            self._shortcut_status_label.setText("将添加到：敌方弃牌区")
            self._shortcut_status_label.setStyleSheet(f"color: {_C_ENEMY}; font-size: 11px; font-weight: bold;")
        else:
            self._shortcut_status_label.setText("请先添加弃牌以自动切换回合")
            self._shortcut_status_label.setStyleSheet(f"color: {_C_MUTED}; font-size: 11px;")

    def _rebuild_shortcuts(self) -> None:
        from PyQt6.QtGui import QShortcut
        from PyQt6.QtGui import QKeySequence
        for sc in self._active_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._active_shortcuts.clear()

        def _sc(key_str, slot):
            sc = QShortcut(QKeySequence(key_str), self)
            sc.activated.connect(slot)
            self._active_shortcuts.append(sc)

        suit_map = {"万": "m", "筒": "p", "条": "s", "字": "z"}
        for suit_label, suit_code in suit_map.items():
            key = self._shortcut_keys.get(suit_label, "")
            if key:
                _sc(key, lambda _=None, c=suit_code: self._switch_shortcut_suit(c))

        for n in range(1, 10):
            _sc(str(n), lambda _=None, v=n: self._shortcut_select(v))

        add_key = self._shortcut_keys.get("添加", "Return")
        undo_key = self._shortcut_keys.get("撤销", "U")
        clear_key = self._shortcut_keys.get("清空", "C")
        _sc(add_key, self._shortcut_add)
        _sc(undo_key, self._shortcut_undo)
        _sc(clear_key, self._shortcut_clear)
        analyze_key = self._shortcut_keys.get("分析", "A")
        if analyze_key:
            _sc(analyze_key, lambda: self.reanalyze_with_ai_requested.emit("retry"))
        toggle_key = self._shortcut_keys.get("切换回合", "Q")
        if toggle_key:
            _sc(toggle_key, self._shortcut_toggle_turn)
        self._install_global_hook()

    def _open_shortcut_config(self) -> None:
        from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence, QKeyEvent

        # 按键录入框：获得焦点后直接按键录入，无需手动输入字符串
        class _KeyCaptureEdit(QLineEdit):
            _MODIFIERS = {
                Qt.Key.Key_Control, Qt.Key.Key_Shift,
                Qt.Key.Key_Alt, Qt.Key.Key_Meta,
            }

            def keyPressEvent(self, e: QKeyEvent):
                if e.key() in self._MODIFIERS:
                    return
                seq = QKeySequence(e.key()).toString()
                if not seq:
                    return
                self.setText(seq)

            def focusInEvent(self, e):
                super().focusInEvent(e)
                self.setPlaceholderText("")
                self.selectAll()

        dlg = QDialog(self)
        dlg.setWindowTitle("快捷键配置")
        form = QFormLayout(dlg)
        hint = QLabel("点击输入框后直接按目标键即可录入")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(hint)
        editors: dict[str, _KeyCaptureEdit] = {}
        for label, default_key in self._shortcut_keys.items():
            ed = _KeyCaptureEdit(default_key)
            ed.setPlaceholderText("点击后按键...")
            ed.setReadOnly(False)
            editors[label] = ed
            form.addRow(label, ed)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        for label, ed in editors.items():
            val = ed.text().strip()
            if val:
                self._shortcut_keys[label] = val
        # 更新牌型按钮文本
        suit_map = {"万": "m", "筒": "p", "条": "s", "字": "z"}
        for suit_label, suit_code in suit_map.items():
            btn = self._suit_btns.get(suit_code)
            if btn:
                key = self._shortcut_keys.get(suit_label, "")
                btn.setText(f"{key}={suit_label}")
        # 更新快捷键说明
        self._shortcut_hint_label.setText(
            f"添加:{self._shortcut_keys.get('添加','Return')}  "
            f"撤销:{self._shortcut_keys.get('撤销','U')}  "
            f"清空:{self._shortcut_keys.get('清空','C')}  "
            f"分析:{self._shortcut_keys.get('分析','A')}  "
            f"切换回合:{self._shortcut_keys.get('切换回合','Q')}  (数字键1-9选牌)"
        )
        self._rebuild_shortcuts()
        self.config_save_requested.emit({"shortcut_keys": dict(self._shortcut_keys)})

    def _format_tiles(self, tiles) -> str:
        if not tiles:
            return "（空）"
        return "  ".join(tile_display(tile.tile_id) for tile in tiles if tile.tile_id)

    def _format_melds(self, melds) -> str:
        if not melds:
            return "（空）"
        type_map = dict(MELD_TYPE_OPTIONS)
        type_map["auto"] = "自动"
        parts: list[str] = []
        for meld in melds:
            label = type_map.get(meld.meld_type, meld.meld_type)
            tile_text = ",".join(tile_display(tile.tile_id) for tile in meld.tiles if tile.tile_id)
            parts.append(f"{label}[{tile_text}]")
        return "  ".join(parts)

    def _rebuild_meld_buttons(self, melds, is_enemy: bool, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not melds:
            layout.addWidget(QLabel("（空）"))
            layout.addStretch()
            return
        type_map = dict(MELD_TYPE_OPTIONS)
        type_map["auto"] = "自动"
        for idx, meld in enumerate(melds):
            label = type_map.get(meld.meld_type, meld.meld_type)
            tile_text = ",".join(tile_display(tile.tile_id) for tile in meld.tiles if tile.tile_id)
            btn = QPushButton(f"{label}[{tile_text}]")
            btn.setToolTip("点击操作")
            btn.clicked.connect(
                lambda _checked, i=idx, e=is_enemy, m=meld: self._on_meld_btn_click(i, e, m)
            )
            layout.addWidget(btn)
        layout.addStretch()

    def _on_meld_btn_click(self, meld_index: int, is_enemy: bool, meld) -> None:
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        modify_act = menu.addAction("修改")
        delete_act = menu.addAction("删除")
        chosen = menu.exec(QCursor.pos())
        if chosen == modify_act:
            self._on_meld_correction_click(meld_index, is_enemy, meld)
        elif chosen == delete_act:
            melds = self._state.enemy_melds if is_enemy else self._state.self_melds
            if meld_index < len(melds):
                m = melds.pop(meld_index)
                if self._is_kan(m.meld_type):
                    self._adjust_remaining(+1)
                key = "delete_enemy_meld" if is_enemy else "delete_self_meld"
                self._record_and_emit(key, {"index": meld_index})
                lo = self._enemy_meld_layout if is_enemy else self._self_meld_layout
                self._rebuild_meld_buttons(melds, is_enemy, lo)

    def _on_meld_correction_click(self, meld_index: int, is_enemy: bool, current_meld) -> None:
        dlg = MeldSelectionDialog("修改副露", parent=self, existing_meld=current_meld)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_meld = dlg.selected_meld()
        melds = self._state.enemy_melds if is_enemy else self._state.self_melds
        if meld_index < len(melds):
            melds[meld_index] = new_meld
            if not is_enemy:
                self._state.self_melds_locked = True
            self._record_and_emit(
                "correct_enemy_meld" if is_enemy else "correct_self_meld",
                {"index": meld_index, "meld_type": new_meld.meld_type,
                 "tiles": [t.tile_id for t in new_meld.tiles]},
            )
            # Emit training signal for each tile in the corrected meld (flat index).
            tiles_per_meld = 4 if new_meld.meld_type.startswith("kan") else 3
            base = meld_index * tiles_per_meld
            for i, tile in enumerate(new_meld.tiles[:tiles_per_meld]):
                if tile.tile_id:
                    self.meld_correction_requested.emit(base + i, tile.tile_id)

    def _render_state(self) -> None:
        baida_tile = self._state.baida_tile or ""
        baida_suit = baida_tile[-1] if baida_tile else ""
        self._baida_suit_combo.blockSignals(True)
        self._baida_suit_combo.setCurrentIndex(max(0, self._baida_suit_combo.findData(baida_suit)))
        self._baida_suit_combo.blockSignals(False)
        self._reload_baida_values()
        self._baida_value_combo.blockSignals(True)
        self._baida_value_combo.setCurrentIndex(max(0, self._baida_value_combo.findData(baida_tile)))
        self._baida_value_combo.blockSignals(False)

        self._remaining_spin.blockSignals(True)
        self._remaining_spin.setValue(self._state.remaining_tiles)
        self._remaining_spin.blockSignals(False)

        self._rebuild_hand_tile_buttons(self._state.self_hand)
        self._rebuild_discard_buttons(self._state.self_discards, False, self._self_discard_layout)
        self._rebuild_discard_buttons(self._state.enemy_discards, True, self._enemy_discard_layout)
        self._rebuild_meld_buttons(self._state.self_melds, False, self._self_meld_layout)
        self._rebuild_meld_buttons(self._state.enemy_melds, True, self._enemy_meld_layout)
        self._recognition_label.setText(f"识别来源：{self._state.recognition_source}")
        self._provider_combo.blockSignals(True)
        self._provider_combo.setCurrentIndex(max(0, self._provider_combo.findData(self._state.vision_provider)))
        self._provider_combo.blockSignals(False)

        # 同步庄家/门风/暗杠显示
        self._dealer_combo.blockSignals(True)
        self._dealer_combo.setCurrentIndex(max(0, self._dealer_combo.findData(self._state.dealer_seat)))
        self._dealer_combo.blockSignals(False)

        self._wind_combo.blockSignals(True)
        self._wind_combo.setCurrentIndex(max(0, self._wind_combo.findData(self._state.self_wind)))
        self._wind_combo.blockSignals(False)

        self._kan_closed_combo.blockSignals(True)
        self._kan_closed_combo.setCurrentIndex(max(0, self._kan_closed_combo.findData(self._state.kan_closed_count)))
        self._kan_closed_combo.blockSignals(False)

        dealer_text = "自家" if self._state.dealer_seat == "self" else "对手"
        wind_text = {"1z": "东", "2z": "南"}.get(self._state.self_wind, self._state.self_wind)
        self._state_summary_label.setText(
            f"当前牌局摘要：庄家={dealer_text} | 门风={wind_text} | "
            f"我方手牌{len(self._state.self_hand)}张 | "
            f"我方弃牌{len(self._state.self_discards)}张 | "
            f"敌方弃牌{len(self._state.enemy_discards)}张 | "
            f"暗杠{self._state.kan_closed_count}次 | "
            f"剩余{self._state.remaining_tiles}张"
        )
        self._update_turn_label()
        self._update_shortcut_status()

    def clear_stream_buffer(self) -> None:
        self._stream_buffer = ""
        self._stream_discard_found = False
        self._summary_edit.clear()
        self._recommended_label.setText("当前推荐出牌：AI 生成中…")
        self._recommended_label.setStyleSheet(f"color:{_C_AI};")

    def append_stream_chunk(self, chunk: str) -> None:
        try:
            self._stream_buffer += chunk
            self._summary_edit.setPlainText(self._stream_buffer)
            # 只在还没找到推荐出牌时做 regex，找到后不再重复搜索
            if not self._stream_discard_found:
                m = re.search(r'"recommended_discard"\s*:\s*"([^"]+)"', self._stream_buffer)
                if m:
                    self._stream_discard_found = True
                    discard_id = m.group(1)
                    tile_name = TILE_NAME_MAP.get(discard_id, discard_id)
                    self._recommended_label.setText(f"当前推荐出牌：{tile_name}")
                    self._recommended_label.setStyleSheet(f"color:{_C_OK}; font-weight:bold;")
        except Exception:
            pass

    def _render_advice(self, advice: BattleAdvice) -> None:
        discard_id = advice.recommended_discard or ""
        discard = TILE_NAME_MAP.get(discard_id, discard_id) if discard_id else "--"
        self._recommended_label.setText(f"当前推荐出牌：{discard}")
        self._recommended_label.setStyleSheet(
            f"color:{_C_OK}; font-weight:bold;" if advice.recommended_discard else ""
        )

        _TYPE_COLORS = {"攻牌": _C_OK, "守牌": _C_WARN, "平衡": _C_SELF}
        st = advice.strategy_type or ""
        color = _TYPE_COLORS.get(st, _C_2ND)
        self._strategy_label.setText(f"策略类型：{st or '--'}")
        self._strategy_label.setStyleSheet(f"color:{color}; font-weight:bold;" if st else "")

        parts: list[str] = []
        if advice.reasoning_summary:
            parts.append(
                f'<p style="color:{_C_TEXT};margin:2px 0">{html.escape(_replace_tile_codes(advice.reasoning_summary))}</p>'
            )
        if advice.forbidden_discards:
            fd = html.escape("、".join(_replace_tile_codes(t) for t in advice.forbidden_discards))
            parts.append(f'<p style="color:{_C_ERR};margin:2px 0">⚠ 禁止出牌：{fd}</p>')
        if advice.risk_notes:
            parts.append(
                f'<p style="color:{_C_WARN};margin:2px 0">⚡ 风险：{html.escape(_replace_tile_codes(advice.risk_notes))}</p>'
            )
        self._summary_edit.setHtml("".join(parts))

        ca = advice.candidate_actions
        if not ca:
            local_candidates = self._state.last_analysis.get("candidates", [])[:3]
            ca = [
                f"打{TILE_NAME_MAP.get(c.get('discard', ''), c.get('discard', ''))}"
                for c in local_candidates if c.get("discard")
            ]
        candidates = " / ".join(_replace_tile_codes(a) for a in ca) if ca else "--"
        self._candidate_label.setText(f"候选动作：{candidates}")
        self._candidate_label.setStyleSheet(f"color:{_C_CAND};" if ca else "")
        if self._state.last_analysis_at:
            timing_parts: list[str] = []
            if self._state.last_recognition_duration_ms > 0:
                timing_parts.append(f"图片识别：{self._state.last_recognition_duration_ms} ms")
            if self._state.last_local_analysis_duration_ms > 0:
                timing_parts.append(f"数据分析：{self._state.last_local_analysis_duration_ms} ms")
            if self._state.last_advice_duration_ms > 0:
                timing_parts.append(f"AI分析：{self._state.last_advice_duration_ms} ms")
            timing_text = "\n" + " | ".join(timing_parts) if timing_parts else ""
            self._meta_label.setText(
                f"最近一次分析：{self._state.last_analysis_at} | 触发：{self._state.last_trigger_reason}{timing_text}"
            )
        else:
            self._meta_label.setText("最近一次分析：--")
        self._analysis_panel.refresh(self._state.last_analysis, advice.recommended_discard)

    def current_state(self) -> BattleState:
        return deepcopy(self._state)

    def set_state(self, state: BattleState) -> None:
        self._state = deepcopy(state)
        self._deepseek_checkbox.blockSignals(True)
        self._deepseek_checkbox.setChecked(self._state.deepseek_enabled)
        self._deepseek_checkbox.blockSignals(False)
        self._render_state()

    def set_advice(self, advice: BattleAdvice) -> None:
        self._render_advice(advice)

    def set_training_in_progress(self) -> None:
        self._train_success_label.setText("⏳ 正在训练中...")
        self._train_success_label.setStyleSheet(f"color: {_C_WARN}; font-size: 11px;")

    def set_train_success_message(self, message: str) -> None:
        self._train_success_label.setText(message)
        self._train_success_label.setStyleSheet(f"color: {_C_OK}; font-size: 11px;")

    def set_error(self, message: str) -> None:
        self._error_label.setText(message)

    def clear_error(self) -> None:
        self._error_label.clear()

    def clear_round_feedback(self) -> None:
        self._recommended_label.setText("当前推荐出牌：--")
        self._summary_edit.clear()
        self._candidate_label.setText("候选动作：--")
        self._meta_label.setText("最近一次分析：--")
        self._error_label.clear()

    @staticmethod
    def _qkey_to_kb(qkey: str) -> str:
        return {
            "Return": "enter", "Space": "space",
            "Delete": "delete", "Backspace": "backspace",
            "Escape": "escape",
        }.get(qkey, qkey.lower())

    def _install_global_hook(self) -> None:
        self._uninstall_global_hook()
        try:
            import keyboard as _kb
        except ImportError:
            return
        # 构建 key_name → action 映射，存到实例变量供槽函数使用
        actions: dict[str, callable] = {}
        suit_map = {"万": "m", "筒": "p", "条": "s", "字": "z"}
        for suit_label, suit_code in suit_map.items():
            k = self._qkey_to_kb(self._shortcut_keys.get(suit_label, ""))
            if k:
                actions[k] = lambda c=suit_code: self._switch_shortcut_suit(c)
        for n in range(1, 10):
            actions[str(n)] = lambda v=n: self._shortcut_select(v)
        for label, fn in [
            ("添加", self._shortcut_add),
            ("撤销", self._shortcut_undo),
            ("清空", self._shortcut_clear),
            ("切换回合", self._shortcut_toggle_turn),
            ("分析", lambda: self.reanalyze_with_ai_requested.emit("retry")),
        ]:
            k = self._qkey_to_kb(self._shortcut_keys.get(label, ""))
            if k:
                actions[k] = fn
        self._global_actions = actions

        # 使用 pyqtSignal 跨线程安全通信（比 QTimer.singleShot 更可靠）
        def _on_key(event):
            if event.event_type != "down":
                return
            if not self._game_in_progress:
                return
            if event.name in self._global_actions:
                self._global_key_pressed.emit(event.name)

        self._global_kb_hook = _kb.hook(_on_key, suppress=False)

    def _on_global_key(self, key_name: str) -> None:
        fn = self._global_actions.get(key_name)
        if fn:
            fn()

    def _uninstall_global_hook(self) -> None:
        hook = getattr(self, "_global_kb_hook", None)
        if hook is not None:
            try:
                import keyboard as _kb
                _kb.unhook(hook)
            except Exception:
                pass
            self._global_kb_hook = None

    def set_game_started(self, started: bool) -> None:
        self._game_in_progress = started
        self._start_btn.setEnabled(not started)
        self._end_btn.setEnabled(started)
        if started:
            self._install_global_hook()
        else:
            self._uninstall_global_hook()

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._start_btn.setEnabled(not busy and not self._game_in_progress)
        self._end_btn.setEnabled(not busy and self._game_in_progress)
        self._config_btn.setEnabled(not busy)
        self._recognize_btn.setEnabled(not busy)
        self._busy_label.setText(message or ("分析中..." if busy else "空闲"))
        if busy and message:
            self._progress_label.setText(f"⧗ {message}")
            self._progress_label.setVisible(True)
        else:
            self._progress_label.setVisible(False)
            self._progress_label.setText("")

    def apply_config(self, config: dict) -> None:
        self._config = deepcopy(config)
        self._state.ai_recognition_enabled = bool(self._config.get("battle", {}).get("ai_recognition_enabled", False))
        self._state.vision_provider = self._config.get("vision", {}).get("provider", "auto")
        self._ai_checkbox.blockSignals(True)
        self._ai_checkbox.setChecked(self._state.ai_recognition_enabled)
        self._ai_checkbox.blockSignals(False)
        self._render_state()
