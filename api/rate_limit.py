"""
Rate limit em memória, janela deslizante por api_key -- protege o pool de
compute compartilhado do MotherDuck de um bug/loop no lado do K.LUME ONE,
não é mecanismo de cobrança (só existe um caller confiável hoje).

Estado em memória de processo único -- se algum dia rodar múltiplos workers
uvicorn, cada worker tem sua própria janela (limitação conhecida, aceitável
no volume atual, não resolvida aqui de propósito).
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._requests: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._requests[key]
            while q and now - q[0] > self.window_seconds:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True
