"""Small dependency-free terminal dashboard; plain output stays readable in logs and CI."""
import os
import shutil
import sys
import threading
import time


class Console:
    def __init__(self, plain=False):
        self.tty = sys.stdout.isatty() and not plain and os.environ.get("TERM") != "dumb"
        self.color = self.tty and "NO_COLOR" not in os.environ
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.started = time.monotonic()
        self.errors = []
        self.total, self.done, self.detail = 1, 0, "Preparing"
        self._thread = None

    def __enter__(self):
        if self.tty:
            self._thread = threading.Thread(target=self._refresh, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.clear()

    def clear(self):
        if self.tty:
            with self._lock:
                sys.stdout.write("\r\033[2K"); sys.stdout.flush()

    def __call__(self, message=""):
        with self._lock:
            if self.tty:
                sys.stdout.write("\r\033[2K")
            print(message, flush=True)

    def heading(self, text):
        self("\n" + (f"\033[1;36m{text}\033[0m" if self.color else text))

    def begin(self, total):
        self.total, self.done = max(1, total), 0
        self.started = time.monotonic()

    def phase(self, detail):
        self.detail = detail
        if not self.tty:
            self(f"  > {detail}")

    def tick(self, detail):
        self.detail = detail

    def advance(self):
        self.done += 1

    def _refresh(self):
        frames = "|/-\\"
        i = 0
        while not self._stop.wait(.15):
            elapsed = time.monotonic() - self.started
            fraction = min(1, self.done / self.total)
            bar = "━" * int(fraction * 18) + "·" * (18 - int(fraction * 18))
            eta = (elapsed / self.done * (self.total-self.done)) if self.done else None
            tail = f"{int(elapsed)}s elapsed" + (f" · ~{int(eta)}s left" if eta is not None else "")
            line = f" {frames[i % 4]} {bar} {self.done}/{self.total}  {tail}  {self.detail}"
            width = max(30, shutil.get_terminal_size((100, 24)).columns - 1)
            with self._lock:
                sys.stdout.write("\r\033[2K" + line[:width]); sys.stdout.flush()
            i += 1
