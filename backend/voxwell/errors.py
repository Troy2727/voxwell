"""Which exception messages a user may see.

Voxwell writes its error messages for the user: its own error classes (AudioError,
TranslationError, ...) and the built-in errors its code raises ("The narrator voice was
deleted."). Messages from Python or a library can hold file paths, URLs or internals; they go to
the log (logs/voxwell.log) and the user sees a fixed message instead.
"""

from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent


def user_message(exc: BaseException) -> str | None:
    """The exception's message if Voxwell wrote it, else None.

    Written by Voxwell means an exception class defined in Voxwell, or any exception raised
    directly by Voxwell's code (the innermost traceback frame is in this package).
    """
    message = str(exc)
    if not message:
        return None
    if type(exc).__module__.startswith("voxwell."):
        return message
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is not None and Path(tb.tb_frame.f_code.co_filename).resolve().is_relative_to(_PACKAGE):
        return message
    return None
