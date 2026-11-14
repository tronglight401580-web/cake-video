"""Recipe storage and renderer configuration across preview and export."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from cake.core.recipe import Recipe, meta
from cake.render.renderer import Renderer
from cake.styles import load_style
from cake.pipeline.export import _configure_renderer


def test_legacy_recipe_roundtrip():
    old = {'style': 'ccd', 'strength': .4, 'retouch': .7,
           'opts': {'spots': .2, 'under': .3, 'keep_moles': False, 'debug': True},
           'skin_protect': .6}
    recipe = Recipe.from_legacy(old)
    assert Recipe.from_dict(recipe.to_dict()).to_dict() == recipe.to_dict()
    assert recipe.retouch.eyes == .3
    assert recipe.skin_protect_scale == .6 / .8
    assert not recipe.for_export().retouch.debug


def test_preview_export_renderer_state():
    from cake.ui.engine import PreviewEngine

    recipe = Recipe.from_legacy({'style': 'none', 'strength': .6, 'retouch': 0,
                                 'opts': {'spots': .8, 'under': .4,
                                          'keep_moles': False, 'debug': True},
                                 'skin_protect': .8})
    preview = Renderer(4, 4, False)
    export = Renderer(4, 4, False)
    try:
        engine = PreviewEngine()
        engine.renderer = preview
        engine.info = SimpleNamespace(path='unused.mp4', fps=30)
        engine.w = engine.h = 4
        engine.analyzer = None
        engine.buf = []
        engine.last = None
        engine._apply_params(dict(style=recipe.style, strength=recipe.strength,
                                  retouch=recipe.retouch.level, spots=recipe.retouch.spots,
                                  eyes=recipe.retouch.eyes,
                                  keep_moles=recipe.retouch.keep_moles,
                                  debug=recipe.retouch.debug,
                                  skin_protect_scale=recipe.skin_protect_scale, demo_tint=.6), force_style=True)
        assert preview.recipe.demo_tint == .6
        _configure_renderer(export, recipe, load_style(recipe.style), 4, 4, 'unused.mp4')
        for key in ('strength', 'retouch', 'spots', 'under', 'mole_keep',
                    'skin_protect_scale'):
            assert getattr(preview, key) == getattr(export, key), key
        assert preview.style.name == export.style.name
        assert preview.debug == 1 and export.debug == 0
        assert not export.recipe.retouch.debug
    finally:
        preview.release()
        export.release()


def test_metadata_builds_controls():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QFormLayout, QWidget
    from cake.ui.param_panel import ParamPanel

    app = QApplication.instance() or QApplication([])
    class Panel(ParamPanel, QWidget):
        pass
    panel = Panel()
    panel.controls = {}
    layout = QFormLayout(panel)
    @dataclass
    class ExtendedRecipe(Recipe):
        glow: float = field(default=.2, metadata=meta('发光', .2, 0, 1, .01, '风格'))

    for name, spec in panel.field_specs(ExtendedRecipe):
        if name != 'style':
            panel._control(name, spec, layout)
    assert set(panel.controls) == {name for name, _ in panel.field_specs(ExtendedRecipe)} - {'style'}
    assert panel.controls['spots'].objectName() == 'spots'
    assert panel.controls['glow'].value() == 20
    panel.close()

def test_skin_protection_tracks_style_offscreen():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QComboBox, QSlider, QLabel, QWidget
    from unittest.mock import patch
    from cake.ui.param_panel import ParamPanel

    app = QApplication.instance() or QApplication([])
    class Panel(ParamPanel, QWidget):
        pass
    panel = Panel()
    panel.style_box = QComboBox()
    panel.style_box.addItems(['ordinary', 'reference'])
    panel.skin_protect = QSlider()
    panel.ref_thumb = QLabel()
    with patch('cake.ui.param_panel.load_style', side_effect=[SimpleNamespace(skin_lut=None, reference=None),
                                                              SimpleNamespace(skin_lut='skin.cube', reference=None)]):
        panel._style_changed()
        assert not panel.skin_protect.isEnabled()
        panel.style_box.setCurrentIndex(1)
        panel._style_changed()
        assert panel.skin_protect.isEnabled()
    panel.close()

def test_queue_elides_long_names_offscreen():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from cake.ui.queue_panel import QueuePanel

    app = QApplication.instance() or QApplication([])
    class Panel(QueuePanel, QWidget):
        def _on_select(self, row):
            pass
    panel = Panel()
    widget = panel._build_queue()
    assert panel.queue.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.queue.textElideMode() == Qt.TextElideMode.ElideRight
    widget.close()
    panel.close()
