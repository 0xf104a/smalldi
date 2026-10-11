"""
`ContextAwareThread`, a thread that runs in the injection context of the code that created it.
"""
import threading

from smalldi import Injector

class ContextAwareThread(threading.Thread):
    """
    A `threading.Thread` that runs its target in the creator's current injection context.

    A plain `threading.Thread` starts in the root context, whatever the thread
    creating it had pushed. `ContextAwareThread` captures the creator's current
    `InjectionContext` in `__init__`, the object itself and not a copy, and
    enters it with `Injector.foreign_context` for the duration of `run()`, so
    the target sees the singletons and instances of the context it was created
    in. Contexts pushed by the target inside `run()` stack on top of it and
    must be closed before the target returns.

    Constructor arguments are those of `threading.Thread`.
    """
    def __init__(self, *args, **kwargs):
        """
        Creates the thread and captures `Injector.get_context()` of the calling thread.

        :param args: passed to `threading.Thread.__init__`
        :param kwargs: passed to `threading.Thread.__init__`
        """
        super().__init__(*args, **kwargs)
        self._sdi_injection_context = Injector.get_context()

    def run(self):
        """
        Runs the thread's target inside the captured context.

        The context is pushed on this thread's own stack and popped when the
        target returns or raises.
        """
        with Injector.foreign_context(self._sdi_injection_context):
            super().run()
