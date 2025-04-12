import asyncio
from typing import Optional

from PyQt6.QtWidgets import QApplication

import asyncio
import functools
from typing import Callable, Any
import inspect

def asyncSlot(*arg_types):
    """Decorator for Qt slots that support async def with flexible argument matching."""
    def decorator(fn: Callable[..., Any]):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Try binding args to the original function
            trimmed_args = list(args)
            while True:
                try:
                    inspect.signature(fn).bind(*trimmed_args, **kwargs)
                except TypeError:
                    if not trimmed_args:
                        break
                    trimmed_args.pop()
                else:
                    task = asyncio.ensure_future(fn(*trimmed_args, **kwargs))
                    task.add_done_callback(_log_task_exception)
                    break
        return wrapper
    return decorator

def _log_task_exception(task: asyncio.Task):
    try:
        task.result()
    except Exception as e:
        print(f"[asyncSlot] Uncaught exception: {e}")



class QtAsyncRunner:
    def __init__(self, app: Optional[QApplication] = None, tick_interval: float = 0.01):
        self.app = app or QApplication.instance() or QApplication([])
        self.tick_interval = tick_interval
        self._task = None
        self._running = False

    async def _run_loop(self):
        """Coroutine to tick the Qt event loop regularly."""
        while self._running:
            self.app.processEvents()
            await asyncio.sleep(self.tick_interval)

    def start(self):
        """Starts the Qt async runner as a background task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stops the Qt event loop coroutine."""
        self._running = False
        if self._task:
            await self._task

    def get_app(self):
        return self.app
