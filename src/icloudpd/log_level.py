import logging
from enum import Enum

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


class LogLevel(Enum):
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    ERROR = "error"

    def __str__(self) -> str:
        return self.name
