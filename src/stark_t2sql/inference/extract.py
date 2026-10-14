"""Exact FR-4.7 text extraction and separate FR-4.8 token-cap refusal.

No parser, SQL validation, query execution or model invocation belongs here.
The prescribed first-delimiter rule intentionally has no SQL-string-literal
awareness; the validator remains responsible for accepting its result.
"""

from __future__ import annotations

from ..contracts import FailureClass
from ..errors import ConfigurationError, GenerationTruncatedError, SQLExtractionError
from .client import GenerationResult


def extract_sql(generation: GenerationResult | str) -> str:
    """Strip, cut at earliest semicolon/triple-backtick, strip, append one ';'.

    Production passes a GenerationResult to retain termination evidence. Plain
    text is accepted for future extraction contract cases, never as proof that
    a real generation escaped its token/time limits. A capped candidate without
    confirmed semicolon completion stops as FC-TRUNCATED-GEN before any parser
    or executor can receive it. Empty extraction is independently FC-EXTRACT.
    """
    if type(generation) is GenerationResult:
        raw_output = generation.raw_output
        token_limit = generation.token_limit_reached
        stopped_semicolon = generation.stopped_semicolon
    elif isinstance(generation, str):
        raw_output = generation
        token_limit = False
        stopped_semicolon = False
    else:
        raise ConfigurationError("Extraction requires internal generation facts or explicit source text.")
    stripped = raw_output.strip()
    semicolon = stripped.find(";")
    backticks = stripped.find("```")
    # A backtick cut alone is no evidence that a capped SQL statement finished.
    has_first_semicolon = semicolon >= 0 and (backticks < 0 or semicolon < backticks)
    if token_limit and not (stopped_semicolon or has_first_semicolon):
        error = GenerationTruncatedError("Generation reached its token cap without confirmed SQL completion.")
        error.raw_output = raw_output
        error.failure_class = FailureClass.TRUNCATED_GEN
        error.generation_ms = generation.generation_ms
        raise error
    positions = [position for position in (semicolon, backticks) if position >= 0]
    candidate = stripped[:min(positions)] if positions else stripped
    candidate = candidate.strip()
    if not candidate:
        error = SQLExtractionError("Generated output is empty after the exact FR-4.7 extraction rule.")
        error.raw_output = raw_output
        error.failure_class = FailureClass.EXTRACT
        if type(generation) is GenerationResult:
            error.generation_ms = generation.generation_ms
        raise error
    return candidate + ";"
