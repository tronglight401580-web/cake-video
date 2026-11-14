"""Thread-safe in-process event delivery."""
from collections import defaultdict
from threading import RLock

class EventBus:
    def __init__(self):
        self._lock = RLock()
        self._subscribers = defaultdict(list)

    def subscribe(self, topic, fn):
        with self._lock:
            self._subscribers[topic].append(fn)
        def unsubscribe():
            with self._lock:
                callbacks = self._subscribers.get(topic, [])
                if fn in callbacks:
                    callbacks.remove(fn)
        return unsubscribe

    def publish(self, topic, **payload):
        with self._lock:
            callbacks = tuple(self._subscribers.get(topic, ()))
        for callback in callbacks:
            callback(**payload)

bus = EventBus()
publish = bus.publish
subscribe = bus.subscribe
