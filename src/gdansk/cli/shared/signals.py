from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from gdansk.task import CommandProcess


async def run_until_signal(process_awaitable: Awaitable[CommandProcess]) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(stop_event.set)

    signals: list[signal.Signals] = [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)

    registered: list[signal.Signals] = []
    for current_signal in signals:
        try:
            loop.add_signal_handler(current_signal, request_stop)
            registered.append(current_signal)
        except NotImplementedError:
            signal.signal(current_signal, lambda _signum, _frame: request_stop())

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
        for current_signal in registered:
            loop.remove_signal_handler(current_signal)
