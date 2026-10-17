"""Load immutable local SQLCoder-7B-2 bytes against actual owner bindings.

R01 supports the official model card's two QUESTION regions and one schema
slot. The owner's provenance record and canonical as-of prefix still have no
defaults. Loading never fetches a template or contacts a model/database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from ..errors import ConfigurationError, MissingDependencyError, SourceReadError
from ..utils.fingerprints import sha256_bytes


def require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConfigurationError(f"An actual lowercase SHA-256 is required for {label}.")
    return value


@dataclass(frozen=True, slots=True)
class ReviewedTemplateContract:
    """Trusted bindings reviewed against the actual model-card/E2 source.

    The question/schema placeholders and QUESTION tags must be copied from the
    actual template, not inferred from this class. ``as_of_line_prefix`` is the
    exact recorded v1 as-of wording preceding the ISO date; the FRD fixes its
    location but does not provide verbatim wording. ``source_reference`` names
    the real local model-card provenance record. It is metadata, never a URL
    that this loader fetches. This declaration is no evidence of an E2 run.
    """

    template_sha256: str
    question_placeholder: str
    schema_placeholder: str
    question_open_tag: str
    question_close_tag: str
    as_of_line_prefix: str
    source_reference: str

    def __post_init__(self) -> None:
        require_sha256(self.template_sha256, label="the verbatim model-card template")
        markers = (
            self.question_placeholder, self.schema_placeholder,
            self.question_open_tag, self.question_close_tag,
        )
        if any(not isinstance(marker, str) or not marker for marker in markers):
            raise MissingDependencyError("Reviewed model-card placeholder and QUESTION tag bindings are unavailable.")
        if len(set(markers)) != len(markers):
            raise ConfigurationError("Reviewed template markers must be distinct.")
        if any(first in second for first in markers for second in markers if first != second):
            raise ConfigurationError("Reviewed template markers may not overlap.")
        if markers != (
            "{user_question}", "{table_metadata_string_DDL_statements}",
            "[QUESTION]", "[/QUESTION]",
        ):
            raise ConfigurationError("The contract contains unreviewed SQLCoder-7B-2 template markers.")
        if (
            not isinstance(self.as_of_line_prefix, str) or not self.as_of_line_prefix
            or "\n" in self.as_of_line_prefix or "\r" in self.as_of_line_prefix
            or any(ord(character) < 32 and character != "\t" for character in self.as_of_line_prefix)
        ):
            raise MissingDependencyError("The exact recorded one-line E2 as-of prefix is required.")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise MissingDependencyError("Actual local model-card provenance is required.")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Immutable exact source bytes and their independently computed digest."""

    source_bytes: bytes = field(repr=False)
    sha256: str
    contract: ReviewedTemplateContract

    def __post_init__(self) -> None:
        if type(self.contract) is not ReviewedTemplateContract:
            raise MissingDependencyError("Reviewed actual model-card bindings are required.")
        if not isinstance(self.source_bytes, bytes) or not self.source_bytes:
            raise MissingDependencyError("The verbatim local SQLCoder model-card template is unavailable.")
        require_sha256(self.sha256, label="the loaded template")
        if sha256_bytes(self.source_bytes) != self.sha256 or self.sha256 != self.contract.template_sha256:
            raise ConfigurationError("Template bytes differ from the frozen model-card source binding.")
        try:
            source = self.source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SourceReadError("The model-card template must be strict UTF-8 source.") from exc
        if source.startswith("\ufeff") or "\r" in source:
            raise ConfigurationError("The model-card source must use UTF-8 without BOM and LF line endings.")

        question_marker = self.contract.question_placeholder
        schema_marker = self.contract.schema_placeholder
        opening_marker = self.contract.question_open_tag
        closing_marker = self.contract.question_close_tag
        expected_counts = (
            (question_marker, 2), (opening_marker, 2), (closing_marker, 2),
            (schema_marker, 1), ("[SQL]", 1),
        )
        for marker, count in expected_counts:
            if source.count(marker) != count:
                raise ConfigurationError("The template requires two QUESTION pairs/slots, one schema slot and one SQL marker.")

        # Consume only original marker spans. A single active region rejects
        # nesting, reversed pairs and crossing pairs before any substitution.
        pattern = "|".join(re.escape(marker) for marker, _ in expected_counts)
        active_opening: int | None = None
        active_question: int | None = None
        regions = 0
        for match in re.finditer(pattern, source):
            marker = match.group()
            if marker == opening_marker:
                if active_opening is not None:
                    raise ConfigurationError("QUESTION tag pairs may not overlap or nest.")
                active_opening, active_question = match.end(), None
            elif marker == question_marker:
                if active_opening is None or active_question is not None:
                    raise ConfigurationError("Each QUESTION region requires exactly one original question slot.")
                if source[active_opening:match.start()].strip():
                    raise ConfigurationError("Only original whitespace may precede the question slot inside its tags.")
                active_question = match.end()
            elif marker == closing_marker:
                if active_opening is None or active_question is None:
                    raise ConfigurationError("QUESTION opening, slot and closing markers must be correctly paired.")
                if source[active_question:match.start()].strip():
                    raise ConfigurationError("Only original whitespace may follow the question slot before its closing tag.")
                regions += 1
                active_opening = active_question = None
            elif marker == schema_marker and active_opening is not None:
                raise ConfigurationError("The schema slot must be outside both QUESTION regions.")
            elif marker == "[SQL]" and (active_opening is not None or regions != 2):
                raise ConfigurationError("The SQL marker must follow both complete QUESTION regions.")
        if active_opening is not None or regions != 2:
            raise ConfigurationError("The template requires two complete non-overlapping QUESTION regions.")
        remaining = source
        for marker, _ in expected_counts:
            remaining = remaining.replace(marker, "")
        if any(character in remaining for character in "{}[]"):
            raise ConfigurationError("The template contains malformed or unreviewed marker text.")

    @property
    def text(self) -> str:
        # No newline conversion, BOM removal, stripping or template mutation.
        return self.source_bytes.decode("utf-8", errors="strict")

    @property
    def newline(self) -> str:
        """The byte-preserving model-card contract permits LF only."""
        return "\n"


def load_template(
    path: str | Path | None, *, contract: ReviewedTemplateContract | None,
    max_bytes: int = 1_048_576,
) -> PromptTemplate:
    """Future runtime binary read; never fetches, creates or substitutes source."""
    if path is None or path == "":
        raise MissingDependencyError("The local verbatim src/inference/prompt_template.txt source is required.")
    if type(contract) is not ReviewedTemplateContract:
        raise MissingDependencyError("Actual model-card template bindings and recorded digest are pending.")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ConfigurationError("The template source-size bound must be a positive integer.")
    try:
        with Path(path).open("rb") as source:
            source_bytes = source.read(max_bytes + 1)
    except FileNotFoundError as exc:
        raise MissingDependencyError("The verbatim local SQLCoder model-card template is absent.") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise SourceReadError("The local model-card template could not be read.") from exc
    if len(source_bytes) > max_bytes:
        raise ConfigurationError("The template exceeds its configured source-size bound.")
    return PromptTemplate(source_bytes, sha256_bytes(source_bytes), contract)
