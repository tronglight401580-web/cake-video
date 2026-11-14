"""Serializable processing parameters."""
from dataclasses import asdict, dataclass, field
import math

def meta(label, default, low=None, high=None, step=None, ui=None, preview_only=False):
    return {'label': label, 'default': default, 'range': (low, high),
            'min': low, 'max': high, 'step': step, 'ui': ui,
            'preview_only': preview_only}

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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if not isinstance(data.get('retouch', {}), dict):
            return cls.from_legacy(data)
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
        return self

    def for_export(self):
        """Return an independent copy without preview-only controls."""
        data = self.to_dict()
        data['retouch']['debug'] = False
        return type(self).from_dict(data)
