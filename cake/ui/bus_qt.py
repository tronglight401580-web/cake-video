"""Deliver core bus events as GUI-thread Qt signals."""
from PySide6.QtCore import QObject, Signal, Qt
from ..core.bus import bus


class QtBusBridge(QObject):
    status = Signal(dict)
    progress = Signal(dict)
    error = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._subscriptions = [bus.subscribe(name, self._emitter(name))
                               for name in ('status', 'progress', 'error')]

    def _emitter(self, name):
        signal = getattr(self, name)
        return lambda **payload: signal.emit(payload)

    def close(self):
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()
