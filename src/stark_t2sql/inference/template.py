"""Read an actual verbatim local model-card template without inventing one.

The authoritative SQLCoder-7B-2 model-card source is unavailable in this source
assignment. The future owner must copy its exact bytes locally and supply the
reviewed placeholder/tag bindings and frozen digest. Those bindings deliberately
have no guessed defaults. Missing input stops before prompt/model work.
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
        for marker in (
            self.contract.question_placeholder, self.contract.schema_placeholder,
            self.contract.question_open_tag, self.contract.question_close_tag,
        ):
            if source.count(marker) != 1:
                raise ConfigurationError("The actual template must contain each reviewed marker exactly once.")
        opening = source.index(self.contract.question_open_tag)
        question = source.index(self.contract.question_placeholder)
        closing = source.index(self.contract.question_close_tag)
        if not opening + len(self.contract.question_open_tag) <= question < closing:
            raise ConfigurationError("The reviewed question slot must be inside the single QUESTION tag pair.")
        if source[question + len(self.contract.question_placeholder):closing].strip():
            raise ConfigurationError("Only original whitespace may follow the question slot before its closing tag.")
        schema = source.index(self.contract.schema_placeholder)
        if opening <= schema < closing:
            raise ConfigurationError("The schema slot must be outside the QUESTION tags.")

    @property
    def text(self) -> str:
        # No newline conversion, BOM removal, stripping or template mutation.
        return self.source_bytes.decode("utf-8", errors="strict")

    @property
    def newline(self) -> str:
        """Use the original template's question-region newline convention."""
        opening = self.text.index(self.contract.question_open_tag)
        closing = self.text.index(self.contract.question_close_tag)
        region = self.text[opening:closing]
        if "\r\n" in region:
            if "\n" in region.replace("\r\n", "") or "\r" in region.replace("\r\n", ""):
                raise ConfigurationError("The template QUESTION region has ambiguous newline conventions.")
            return "\r\n"
        if "\r" in region:
            raise ConfigurationError("Unsupported newline convention in the template QUESTION region.")
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
