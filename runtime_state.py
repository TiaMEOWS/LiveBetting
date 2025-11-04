from datetime import datetime
import threading

class PauseState:
    def __init__(self):
        self._lock = threading.Lock()
        self._paused = False

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self):
        with self._lock:
            self._paused = False

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

PAUSE_STATE = PauseState()