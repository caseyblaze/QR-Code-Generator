import time


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self._ttl_seconds = ttl_seconds
        self._data = {}

    def get(self, key):
        item = self._data.get(key)
        if not item:
            return None
        value, expires_at = item
        if expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key, value) -> None:
        self._data[key] = (value, time.time() + self._ttl_seconds)

    def delete(self, key) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()
