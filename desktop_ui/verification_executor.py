"""One dedicated thread for the stateful Playwright verification browser."""

from __future__ import annotations

from concurrent.futures import Future
from queue import Queue
from threading import Thread


class VerificationExecutor:
    """Serialize the entire interactive-browser lifecycle on one OS thread."""

    def __init__(self, facade: object) -> None:
        self._facade = facade
        self._commands: Queue[tuple[str, str, Future[None]] | None] = Queue()
        self._thread = Thread(target=self._run, name="verification-browser", daemon=True)
        self._thread.start()

    def submit(self, action: str, review_id: str) -> Future[None]:
        if action not in {"begin", "finish", "defer"}:
            raise ValueError("unknown verification action")
        result: Future[None] = Future()
        self._commands.put((action, review_id, result))
        return result

    def shutdown(self) -> None:
        if not self._thread.is_alive():
            return
        try:
            self.submit("defer", "").result(5)
        except (AttributeError, RuntimeError):
            # Narrow shell facades need not implement interactive verification.
            pass
        self._commands.put(None)
        self._thread.join(5)

    def _run(self) -> None:
        while (command := self._commands.get()) is not None:
            action, review_id, result = command
            try:
                getattr(self._facade, f"{action}_verification")(review_id)
            except BaseException as error:
                result.set_exception(error)
            else:
                result.set_result(None)
