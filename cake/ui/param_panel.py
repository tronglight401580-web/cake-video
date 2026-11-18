from __future__ import annotations
import os
import threading
from dataclasses import fields
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QGroupBox, QFormLayout, QComboBox, QCheckBox, QLineEdit, QProgressBar,
    QFileDialog, QSlider, QMessageBox)
from ..styles import list_styles, load_style
from ..core.recipe import Recipe, RetouchCfg, section_types
from ..core import config
from .presets import load_presets, save_presets
from .queue_panel import ROLE_PATH, ROLE_SETTINGS, _thumbnail

def _slider(lo, hi, val):
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s

class ParamPanel:
    @staticmethod
    def field_specs(recipe_type=Recipe):
        """Flatten UI fields from Recipe and its retouch section."""
        Recipe()  # ensure built-in sections have registered
        for item in fields(recipe_type):
            if item.metadata.get('ui') and (config.CAKE_DEV or not item.metadata.get('dev_only')):
                yield item.name, item
            elif item.name == 'retouch':
                for child in fields(RetouchCfg):
                    if child.metadata.get('ui') and (config.CAKE_DEV or not child.metadata.get('dev_only')):
                        yield child.name, child
        for section, cls in section_types().items():
            for child in fields(cls):
                if child.metadata.get('ui') and (config.CAKE_DEV or not child.metadata.get('dev_only')):
                    yield f'{section}.{child.name}', child

    def _control(self, name, spec, layout, initial=None):
        md = spec.metadata
        default = md['default'] if initial is None else initial
        if isinstance(default, bool):
            control = QCheckBox(md['label'])
            control.setChecked(default)
            layout.addRow(control)
        else:
            scale = 80 if name == 'skin_protect_scale' else 100
            control = _slider(round((md['min'] or 0) * scale),
                              round(md['max'] * scale),
                              round((default or 0) * scale))
            value = QLabel()
            layout.addRow(self._labeled(md['label'], control, value))
            setattr(self, f'{name}_lbl', value)
        control.setObjectName(name)
        self.controls[name] = control
        return control

    def _build_params(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(290)
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 8, 8, 8)

        g = QGroupBox("我的预设")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.setPlaceholderText("（无）")
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self._apply_preset)
        row.addWidget(self.preset_box, 1)
        row.addWidget(b_apply)
        gv.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("存为预设", self._save_preset), ("删除预设", self._delete_preset),
                         ("应用到全部", self._apply_to_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        gv.addLayout(row)
        v.addWidget(g)
        self._reload_presets()

        g = QGroupBox("风格")
        f = QFormLayout(g)
        self.style_box = QComboBox()
        for st in list_styles():
            self.style_box.addItem(st.title or st.name, st.name)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData("film_warm")))
        self.style_box.currentIndexChanged.connect(self.param_timer.start)
        self.controls = {}
        f.addRow("风格", self.style_box)
        self.controls['style'] = self.style_box
        self.ref_thumb = QLabel()
        f.addRow(self.ref_thumb)
        self.ref_button = QPushButton("\u53c2\u8003\u56fe\u8ffd\u8272")
        self.ref_button.clicked.connect(self._choose_reference)
        f.addRow(self.ref_button)
        self.codex_button = QPushButton("Codex AI 追色")
        self.codex_button.setToolTip("用提示词让 Codex 给当前画面调色，再自动拟合成追色风格")
        self.codex_button.clicked.connect(self._open_codex)
        f.addRow(self.codex_button)
        specs = dict(self.field_specs())
        self.skin_protect = self._control('skin_protect_scale', specs['skin_protect_scale'], f, 1.0)
        self.skin_lbl = self.skin_protect_scale_lbl
        self.style_box.currentIndexChanged.connect(self._style_changed)
        self.skin_protect.valueChanged.connect(self.param_timer.start)
        self.skin_protect.valueChanged.connect(self._update_labels)
        self._style_changed()
        self.strength = self._control('strength', specs['strength'], f)
        for name, spec in self.field_specs():
            if name not in self.controls and spec.metadata['ui'] == '风格':
                control = self._control(name, spec, f)
                if isinstance(control, QCheckBox):
                    control.toggled.connect(self.param_timer.start)
                else:
                    control.valueChanged.connect(self.param_timer.start)
                    label = getattr(self, f'{name}_lbl')
                    label.setText(str(control.value()))
                    control.valueChanged.connect(lambda value, label=label: label.setText(str(value)))
        v.addWidget(g)

        g = QGroupBox("人像精修")
        f = QFormLayout(g)
        self.retouch = self._control('level', specs['level'], f)
        self.retouch_lbl = self.level_lbl
        self.spots = self._control('spots', specs['spots'], f, .8)
        self.eyes = self._control('eyes', specs['eyes'], f, .45)
        self.keep_moles = self._control('keep_moles', specs['keep_moles'], f)
        self.debug = self._control('debug', specs['debug'], f)
        for name, spec in self.field_specs():
            if name not in self.controls and spec.metadata['ui'] == '人像精修':
                self._control(name, spec, f)
        v.addWidget(g)
        known_groups = {'\u98ce\u683c', '\u4eba\u50cf\u7cbe\u4fee'}
        for group in dict.fromkeys(spec.metadata['ui'] for _, spec in self.field_specs()):
            if group in known_groups:
                continue
            box = QGroupBox(group)
            form = QFormLayout(box)
            for name, spec in self.field_specs():
                if spec.metadata['ui'] == group and name not in self.controls:
                    self._control(name, spec, form)
            v.addWidget(box)
        for name, spec in self.field_specs():
            if '.' in name:
                control = self.controls[name]
                signal = control.toggled if isinstance(control, QCheckBox) else control.valueChanged
                signal.connect(self.param_timer.start)
        self.spots.sliderMoved.connect(lambda _: setattr(self, "spots_touched", True))
        self.eyes.sliderMoved.connect(lambda _: setattr(self, "eyes_touched", True))
        self.retouch.valueChanged.connect(self._follow_retouch)
        for s in (self.strength, self.retouch, self.spots, self.eyes):
            s.valueChanged.connect(self.param_timer.start)
            s.valueChanged.connect(self._update_labels)
        for c in (self.keep_moles, self.debug):
            c.toggled.connect(self.param_timer.start)
        self._update_labels()

        g = QGroupBox("导出")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("默认：视频所在文件夹\\cake_out")
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._choose_out)
        row.addWidget(self.out_dir, 1)
        row.addWidget(b)
        gv.addLayout(row)
        row = QHBoxLayout()
        self.export_one = QPushButton("导出当前")
        self.export_all = QPushButton("全部导出")
        self.export_all.setObjectName("primary")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.export_one.clicked.connect(lambda: self._export(all_items=False))
        self.export_all.clicked.connect(lambda: self._export(all_items=True))
        self.cancel_btn.clicked.connect(self._cancel_export)
        for b in (self.export_one, self.export_all, self.cancel_btn):
            row.addWidget(b)
        gv.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        self.open_out = QPushButton("打开输出文件夹")
        self.open_out.setEnabled(False)
        self.open_out.clicked.connect(lambda: os.startfile(self.last_out_dir))
        gv.addWidget(self.progress)
        gv.addWidget(self.export_status)
        gv.addWidget(self.open_out)
        v.addWidget(g)
        v.addStretch(1)
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setStyleSheet("color:#7d828a; font-size:12px;")
        v.addWidget(self.info_lbl)
        return w

    @staticmethod
    def _labeled(name: str, slider: QSlider, value_lbl: QLabel) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(name)
        lbl.setFixedWidth(60)
        value_lbl.setFixedWidth(36)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(lbl)
        h.addWidget(slider, 1)
        h.addWidget(value_lbl)
        return w

    def _choose_reference(self):
        item = self.queue.currentItem()
        if item is None:
            self.statusBar().showMessage("\u8bf7\u5148\u9009\u62e9\u89c6\u9891")
            return
        ref, _ = QFileDialog.getOpenFileName(self, "\u9009\u62e9\u53c2\u8003\u56fe", "", "\u56fe\u7247 (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not ref:
            return
        self.ref_button.setEnabled(False)
        self.statusBar().showMessage("\u6b63\u5728\u751f\u6210\u53c2\u8003\u56fe\u98ce\u683c...")
        self.ref_worker = ReferenceWorker(ref, item.data(ROLE_PATH))
        self.ref_worker.ready.connect(self._reference_ready)
        self.ref_worker.failed.connect(lambda err: self.statusBar().showMessage("\u751f\u6210\u5931\u8d25: " + err))
        self.ref_worker.finished.connect(lambda: self.ref_button.setEnabled(True))
        self.ref_worker.start()

    def _open_codex(self):
        item = self.queue.currentItem()
        if item is None:
            self.statusBar().showMessage("请先选择视频")
            return
        from .codex_dialog import CodexDialog
        t = self.timeline.value() / 1000 * self.duration if self.duration > 0 else 0.0
        self.codex_dlg = CodexDialog(self, item.data(ROLE_PATH), t)
        self.codex_dlg.style_ready.connect(self._reference_ready)
        self.codex_dlg.show()

    def _reference_ready(self, name, title):
        idx = self.style_box.findData(name)
        if idx < 0:
            self.style_box.addItem(title, name)
            idx = self.style_box.findData(name)
        self.style_box.setCurrentIndex(idx)
        self._style_changed()
        self.statusBar().showMessage("\u53c2\u8003\u56fe\u98ce\u683c\u5df2\u751f\u6210")

    def _style_changed(self):
        st = load_style(self.style_box.currentData())
        self.skin_protect.setEnabled(bool(st.skin_lut))
        pix = QPixmap(st.reference) if st.reference else QPixmap()
        self.ref_thumb.setPixmap(pix.scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _follow_retouch(self, v: int):
        r = v / 100
        if not self.spots_touched:
            self.spots.setValue(round(min(1.0, 1.6 * r) * 100))
        if not self.eyes_touched:
            self.eyes.setValue(round(min(0.8, 0.9 * r) * 100))

    def _update_labels(self):
        self.skin_lbl.setText(f"{self.skin_protect.value()}%")
        self.strength_lbl.setText(f"{self.strength.value()}%")
        self.retouch_lbl.setText(str(self.retouch.value()))
        self.spots_lbl.setText(str(self.spots.value()))
        self.eyes_lbl.setText(str(self.eyes.value()))

    def settings(self) -> dict:
        recipe = Recipe.from_dict(self._section_settings) if hasattr(self, '_section_settings') else Recipe()
        retouch_names = {item.name for item in fields(RetouchCfg)}
        for name, _ in self.field_specs():
            control = self.controls[name]
            if name == 'style':
                value = control.currentData()
            elif isinstance(control, QCheckBox):
                value = control.isChecked()
            elif (name == 'spots' and not self.spots_touched or
                  name == 'eyes' and not self.eyes_touched):
                value = None
            else:
                value = control.value() / (80 if name == 'skin_protect_scale' else 100)
            if '.' in name:
                section, attr = name.split('.', 1)
                setattr(recipe.sections[section], attr, value)
            else:
                setattr(recipe.retouch if name in retouch_names else recipe, name, value)
        return recipe.to_dict()

    def _send_params(self):
        s = self.settings()
        self.engine.set_recipe(Recipe.from_dict(s))
        it = self.queue.currentItem()
        if it is not None and not self._applying:
            it.setData(ROLE_SETTINGS, s)          # every clip remembers its own settings

    def apply_settings(self, s: dict):
        """Push a settings dict into the widgets (one engine update at the end)."""
        recipe = s if isinstance(s, Recipe) else (Recipe.from_dict(s)
                  if isinstance(s.get('retouch'), dict) else Recipe.from_legacy(s))
        self._section_settings = recipe.to_dict()
        self._applying = True
        try:
            self.style_box.setCurrentIndex(max(0, self.style_box.findData(recipe.style)))
            self.strength.setValue(round(recipe.strength * 100))
            self.retouch.setValue(round(recipe.retouch.level * 100))
            self.skin_protect.setValue(round(recipe.skin_protect_scale * 80))
            self.spots_touched = recipe.retouch.spots is not None
            self.eyes_touched = recipe.retouch.eyes is not None
            self.spots.setValue(round((recipe.retouch.spots if self.spots_touched else min(1., 1.6 * recipe.retouch.level)) * 100))
            self.eyes.setValue(round((recipe.retouch.eyes if self.eyes_touched else min(.8, .9 * recipe.retouch.level)) * 100))
            self.keep_moles.setChecked(recipe.retouch.keep_moles)
            self.debug.setChecked(recipe.retouch.debug)
            for name, _ in self.field_specs():
                if name in {'style', 'strength', 'skin_protect_scale', 'level', 'spots',
                            'eyes', 'keep_moles', 'debug'}:
                    continue
                control = self.controls[name]
                if '.' in name:
                    section, attr = name.split('.', 1)
                    value = getattr(recipe.sections[section], attr)
                else:
                    value = getattr(recipe.retouch if hasattr(recipe.retouch, name) else recipe, name)
                if isinstance(control, QCheckBox):
                    control.setChecked(value)
                else:
                    control.setValue(round(value * 100))
        finally:
            self._applying = False
        self.param_timer.stop()
        self._send_params()

    def _reload_presets(self, select: str | None = None):
        self.presets = load_presets()
        self.preset_box.clear()
        for name in self.presets:
            self.preset_box.addItem(name)
        if select:
            self.preset_box.setCurrentText(select)

    def _save_preset(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "存为预设", "预设名称：",
                                        text=self.style_box.currentText())
        if ok and name.strip():
            self.presets[name.strip()] = self.settings()
            save_presets(self.presets)
            self._reload_presets(select=name.strip())
            self.statusBar().showMessage(f"已保存预设「{name.strip()}」")

    def _apply_preset(self):
        s = self.presets.get(self.preset_box.currentText())
        if s:
            self.apply_settings(s)

    def _delete_preset(self):
        name = self.preset_box.currentText()
        if name in self.presets:
            del self.presets[name]
            save_presets(self.presets)
            self._reload_presets()

    def _apply_to_all(self):
        s = self.settings()
        for r in range(self.queue.count()):
            self.queue.item(r).setData(ROLE_SETTINGS, s)
        self.statusBar().showMessage(f"当前参数已应用到全部 {self.queue.count()} 段视频")


class ReferenceWorker(QThread):
    ready = Signal(str, str)
    failed = Signal(str)

    def __init__(self, ref, clip):
        super().__init__()
        self.ref, self.clip = ref, clip

    def run(self):
        try:
            from ..refcolor import build_reference_style
            st = build_reference_style(self.ref, [self.clip])
            self.ready.emit(st.name, st.title)
        except Exception as e:
            self.failed.emit(str(e))
