"""
Logging Configuration.
Sets up the standard python logging module and provides an asynchronous logger wrapper
to prevent blocking the main event loop during high-volume logging.
"""
import logging
import asyncio
from functools import partial

def setup_logging():
    logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
    logging.getLogger("SERVER").setLevel(logging.WARNING)
    logging.getLogger("DATABASE").setLevel(logging.INFO)
    logging.getLogger("SETUP").setLevel(logging.ERROR)
    logging.getLogger("API").setLevel(logging.DEBUG)
    logging.getLogger("WORKER").setLevel(logging.INFO)
    logging.getLogger("FILESERVICE").setLevel(logging.INFO)   
    logging.info("Logging is set up.")


class AsyncLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def __getattr__(self, name):
        return getattr(self._logger, name)

    async def _log_async(self, level, msg, *args, **kwargs):
        loop = asyncio.get_running_loop()
        func = partial(self._logger.log, level, msg, *args, **kwargs)
        await loop.run_in_executor(None, func)

    async def ainfo(self, msg, *args, **kwargs):
        await self._log_async(logging.INFO, msg, *args, **kwargs)

    async def aerror(self, msg, *args, **kwargs):
        await self._log_async(logging.ERROR, msg, *args, **kwargs)

    async def awarning(self, msg, *args, **kwargs):
        await self._log_async(logging.WARNING, msg, *args, **kwargs)

    async def adebug(self, msg, *args, **kwargs):
        await self._log_async(logging.DEBUG, msg, *args, **kwargs)

    async def acritical(self, msg, *args, **kwargs):
        await self._log_async(logging.CRITICAL, msg, *args, **kwargs)


def get_logger(name: str) -> AsyncLogger:
    return AsyncLogger(name)