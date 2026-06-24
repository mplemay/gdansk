from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from gdansk.task import CommandProcess

type HandlerKind = Literal["loop", "stdlib"]


def _register_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    request_stop: Callable[[], None],
) -> list[tuple[signal.Signals, HandlerKind]]:
    signals: list[signal.Signals] = [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)

    handlers: list[tuple[signal.Signals, HandlerKind]] = []

    def _on_signal(_signum: int, _frame: object) -> None:
        request_stop()

    def _use_stdlib_handler(sig: signal.Signals) -> None:
        signal.signal(sig, _on_signal)
        handlers.append((sig, "stdlib"))

    for current_signal in signals:
        if sys.platform == "win32" and current_signal is signal.SIGBREAK:
            _use_stdlib_handler(current_signal)
            continue
        try:
            loop.add_signal_handler(current_signal, request_stop)
            handlers.append((current_signal, "loop"))
        except NotImplementedError:
            _use_stdlib_handler(current_signal)
    return handlers


def _unregister_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    handlers: list[tuple[signal.Signals, HandlerKind]],
) -> None:
    for current_signal, kind in handlers:
        if kind == "loop":
            loop.remove_signal_handler(current_signal)
        else:
            signal.signal(current_signal, signal.SIG_DFL)


async def run_until_signal(process_awaitable: Awaitable[CommandProcess]) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(stop_event.set)

    handlers = _register_signal_handlers(loop, request_stop)

    process: CommandProcess | None = None
    stop_waiter: asyncio.Task[bool] | None = None
    try:
        process = await process_awaitable
        stop_waiter = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {process.task, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_waiter in done:
            await process.stop()
        else:
            await process.wait()
    finally:
        if process is not None and process.is_running:
            await process.stop()
        if stop_waiter is not None:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter
        _unregister_signal_handlers(loop, handlers)
