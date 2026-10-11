import threading

from smalldi import Injector

class ContextAwareThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sdi_injection_context = Injector.get_context()

    def run(self):
        with Injector.foreign_context(self._sdi_injection_context):
            super().run()
