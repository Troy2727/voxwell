"""Language follow: which language an agent answers a turn in.

An agent with follow_languages answers in the language the user speaks, when that language is
allowed and the turn is clear enough to trust. Short or uncertain turns ("ok", a cough heard as a
word) never move it, so it does not flip back and forth.
"""

MIN_CONFIDENCE = 0.75  # Whisper's probability for the detected language
MIN_SWITCH_SECONDS = 1.5  # audio length of the turn
MIN_SWITCH_CHARS = 4  # non-space characters in the transcript


def allowed(agent) -> list[str]:
    """The agent's primary language, then the languages it may follow the user into."""
    # Saving tidies follow_languages, but a hand-edited file may still repeat the primary.
    return [agent.language, *(code for code in dict.fromkeys(agent.follow_languages) if code != agent.language)]


def choose(allowed_codes: list[str], current: str, detected: str, confidence: float, seconds: float, text: str) -> str:
    """The language for this turn: `detected` when the turn clearly is in an allowed language, else `current`."""
    if len(allowed_codes) < 2:
        return allowed_codes[0]
    if detected == current or detected not in allowed_codes:
        return current
    clear = (
        confidence >= MIN_CONFIDENCE
        and seconds >= MIN_SWITCH_SECONDS
        and sum(not c.isspace() for c in text) >= MIN_SWITCH_CHARS
    )
    return detected if clear else current
