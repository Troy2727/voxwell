import json

import pytest

from voxwell.errors import user_message
from voxwell.features.dictation.engine import AudioError
from voxwell.paths import child_path


def raised(fn):
    try:
        fn()
    except Exception as exc:
        return exc
    pytest.fail("expected an exception")


def test_voxwells_own_error_classes_are_shown():
    assert user_message(AudioError("Could not decode the audio.")) == "Could not decode the audio."


def test_a_builtin_error_raised_by_voxwells_code_is_shown(tmp_path):
    exc = raised(lambda: child_path(tmp_path, "../escape"))  # ValueError raised in voxwell/paths.py
    assert isinstance(exc, ValueError) and user_message(exc) == "Not a file name: '../escape'"


def test_an_error_raised_inside_a_library_is_not_shown():
    exc = raised(lambda: json.loads("{"))  # a ValueError, but raised by the json library
    assert isinstance(exc, ValueError) and user_message(exc) is None


def test_an_empty_message_is_not_shown():
    assert user_message(AudioError("")) is None
