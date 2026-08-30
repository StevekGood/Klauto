from core.logging import StructuredLogger

_logger_instance = None

def get_logger() -> StructuredLogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = StructuredLogger()
    return _logger_instance