"""Serializable processing parameters."""
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from copy import deepcopy
import math

def meta(label, default, low=None, high=None, step=None, ui=None, preview_only=False, dev_only=False):
    return {'label': label, 'default': default, 'range': (low, high),
            'min': low, 'max': high, 'step': step, 'ui': ui,
            'preview_only': preview_only, 'dev_only': dev_only}

_sections = {}

def register_section(name):
    def register(cls):
        if not name or name in _sections or not is_dataclass(cls):
            raise ValueError(f'invalid or duplicate section: {name}')
        _sections[name] = cls
        return cls
    return register

def section_types():
    return dict(_sections)

def _builtin_sections():
    from ..render.passes import demo_tint  # register built-in sections

@dataclass
class RetouchCfg:
    level: float = field(default=.5, metadata=meta('磨皮', .5, 0, 1, .01, '人像精修'))
    spots: float | None = field(default=None, metadata=meta('祛痘淡斑', None, 0, 1, .01, '人像精修'))
    eyes: float | None = field(default=None, metadata=meta('黑眼圈', None, 0, 1, .01, '人像精修'))
    keep_moles: bool = field(default=True, metadata=meta('保留痣', True, ui='人像精修'))
    debug: bool = field(default=False, metadata=meta('标记检测结果', False, ui='人像精修', preview_only=True))

@dataclass
class Recipe:
    style: str = field(default='none', metadata=meta('风格', 'none', ui='风格'))
    strength: float = field(default=1., metadata=meta('强度', 1., 0, 1.5, .01, '风格'))
    retouch: RetouchCfg = field(default_factory=RetouchCfg, metadata=meta('精修', None))
    skin_protect_scale: float = field(default=1., metadata=meta('肤色保护', 1., 0, 1.25, .01, '风格'))
    version: int = field(default=1, metadata=meta('版本', 1))

    sections: dict = field(default_factory=dict)

    def __post_init__(self):
        _builtin_sections()
        for name, cls in _sections.items():
            value = self.sections.get(name, {})
            if isinstance(value, dict):
                self.sections[name] = cls(**value)
            elif not isinstance(value, cls):
                raise ValueError(f'invalid section: {name}')

    def __getattr__(self, name):
        sections = self.__dict__.get('sections', {})
        if name in sections:
            return sections[name]
        raise AttributeError(name)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if not isinstance(data.get('retouch', {}), dict):
            return cls.from_legacy(data)
        legacy_tint = data.pop('demo_tint', None)
        data['sections'] = deepcopy(data.get('sections', {}))
        if legacy_tint is not None:
            data['sections'].setdefault('demo_tint', {}).setdefault('amount', legacy_tint)
        data['retouch'] = RetouchCfg(**data.get('retouch', {}))
        data.setdefault('version', 1)
        obj = cls(**data)
        obj.validate()
        return obj

    @classmethod
    def from_legacy(cls, data):
        opts = data.get('opts') or {}
        obj = cls(style=data.get('style', 'none'), strength=data.get('strength', 1.),
                  retouch=RetouchCfg(level=data.get('retouch', .5), spots=opts.get('spots'),
                                     eyes=opts.get('under', opts.get('eyes')),
                                     keep_moles=opts.get('keep_moles', True), debug=opts.get('debug', False)),
                  skin_protect_scale=data.get('skin_protect_scale', data.get('skin_protect', .8) / .8))
        obj.sections.update(deepcopy(data.get('sections', {})))
        if 'demo_tint' in data:
            obj.sections.setdefault('demo_tint', {}).update({'amount': data['demo_tint']}) if isinstance(obj.sections.get('demo_tint'), dict) else setattr(obj.demo_tint, 'amount', data['demo_tint'])
        obj.__post_init__()
        obj.validate()
        return obj

    def validate(self):
        if not isinstance(self.style, str) or not self.style:
            raise ValueError('style must be a nonempty string')
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError('invalid recipe version')
        for value, low, high, name in ((self.strength, 0, 1.5, 'strength'),
                                       (self.skin_protect_scale, 0, 1.25, 'skin_protect_scale'),
                                       (self.retouch.level, 0, 1, 'level'),
                                       (self.retouch.spots, 0, 1, 'spots'),
                                       (self.retouch.eyes, 0, 1, 'eyes')):
            if value is None and name in ('spots', 'eyes'):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'invalid {name}')
        if not isinstance(self.retouch.keep_moles, bool) or not isinstance(self.retouch.debug, bool):
            raise ValueError('retouch flags must be boolean')
        for name, cls in _sections.items():
            section = self.sections.get(name)
            if not isinstance(section, cls):
                raise ValueError(f'invalid section: {name}')
            for item in fields(cls):
                value, md = getattr(section, item.name), item.metadata
                low, high = md.get('min'), md.get('max')
                if isinstance(item.default, bool):
                    if not isinstance(value, bool):
                        raise ValueError(f'invalid {name}.{item.name}')
                elif low is not None and high is not None and value is not None:
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                        raise ValueError(f'invalid {name}.{item.name}')
        return self

    def for_export(self):
        """Return an independent copy without preview-only controls."""
        data = self.to_dict()
        data['retouch']['debug'] = False
        for name, cls in _sections.items():
            for item in fields(cls):
                if item.metadata.get('preview_only'):
                    data['sections'][name][item.name] = item.default
        return type(self).from_dict(data)
