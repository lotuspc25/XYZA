import logging
from typing import Any, Callable

from PyQt5.QtCore import QObject, pyqtSignal, QRunnable

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    progress = pyqtSignal(str, int)
    result = pyqtSignal(object)
    error = pyqtSignal(str, str)
    finished = pyqtSignal()


class WorkerRunnable(QRunnable):
    """
    Generic QRunnable wrapper to execute a callable off the UI thread.
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    def run(self):
        try:
            result = self.fn(self, *self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            logger.exception("Async worker failed")
            self.signals.error.emit("İşlem başarısız", str(exc))
        finally:
            self.signals.finished.emit()
