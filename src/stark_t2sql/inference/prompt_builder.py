"""FR-3/FR-4 prompt assembly over immutable, actually supplied source.

NFR-6 assigns prompt-builder authorship to the human author. Prompt 4 grants a
narrow explicit exception for this Codex draft, without modifying the FRD or
authorizing any execution. A prompt is context minimization, never security.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..context.builder import CompiledContext
from ..contracts import ExecutionMode
from ..errors import ConfigurationError, HarnessSafetyStopError
from ..utils.fingerprints import sha256_bytes, sha256_context
from .template import PromptTemplate


@dataclass(frozen=True, slots=True)
class BuiltPrompt:
    """Internal model input and fingerprints; never a persona response field."""

    text: str = field(repr=False)
    prompt_version: int
    template_sha256: str
    ddl_sha256: str
    semantic_sha256: str
    rendered_sha256: str
    scored: bool = True


def _replace_original_slots(source: str, replacements: tuple[tuple[str, str], ...]) -> str:
    """Replace original source spans once; inserted question text is never parsed.

    str.format, chained str.replace and format_map could treat user braces or
    inserted marker text as new slots. Source span assembly preserves all actual
    model-card bytes outside the reviewed substitution locations.
    """
    spans = sorted((source.index(marker), marker, value) for marker, value in replacements)
    pieces: list[str] = []
    position = 0
    for start, marker, value in spans:
        if start < position:
            raise ConfigurationError("Reviewed template replacement spans overlap.")
        pieces.extend((source[position:start], value))
        position = start + len(marker)
    pieces.append(source[position:])
    return "".join(pieces)


def build_prompt(template: PromptTemplate, context: CompiledContext) -> BuiltPrompt:
    """Render v1 frozen full DDL or v2 physical+semantic metadata in existing slots.

    v1 accepts only the issued E2 harness context profile and inserts its DDL
    exactly as supplied, including BOMs/CRLFs/trailing whitespace. v2 combines
    the context builder's governed physical and semantic blocks in the actual
    model-card schema slot. The QUESTION as-of line follows the unchanged input
    question directly and stays before the actual closing QUESTION tag.
    """
    if type(template) is not PromptTemplate or type(context) is not CompiledContext:
        raise ConfigurationError("Prompt assembly requires typed immutable template and compiled context inputs.")
    if sha256_bytes(template.source_bytes) != template.sha256:
        raise ConfigurationError("The immutable template source binding is inconsistent.")
    request = context.request
    if context.prompt_version == 1:
        if (
            context.profile != "E2_FROZEN_BASELINE" or request.mode is not ExecutionMode.UNCONTROLLED
            or context.semantic_text or context.semantic_catalog_sha256 is not None
        ):
            raise HarnessSafetyStopError("Version 1 is reserved for the frozen full-schema, no-semantics E2 harness profile.")
        metadata = context.ddl
    elif context.prompt_version == 2:
        if context.profile == "E5_ROLE_FILTERED":
            if request.mode not in {ExecutionMode.FULL, ExecutionMode.NO_VALIDATOR}:
                raise HarnessSafetyStopError("The filtered v2 context and request profile differ.")
        elif context.profile == "E5_NO_PROMPT_FILTER":
            if request.mode is not ExecutionMode.NO_PROMPT_FILTER:
                raise HarnessSafetyStopError("The v2 full-context ablation requires the isolated harness profile.")
        else:
            raise ConfigurationError("Unknown compiled version 2 context profile.")
        if not context.semantic_text or context.semantic_catalog_sha256 is None:
            raise ConfigurationError("Version 2 requires the separately filtered governed semantic block.")
        metadata = context.ddl + template.newline + template.newline + context.semantic_text
    else:
        raise ConfigurationError("The prompt version has no reviewed template behavior.")
    question = request.question + template.newline + template.contract.as_of_line_prefix + request.as_of_date.isoformat()
    rendered = _replace_original_slots(template.text, (
        (template.contract.question_placeholder, question),
        (template.contract.schema_placeholder, metadata),
    ))
    return BuiltPrompt(
        rendered, context.prompt_version, template.sha256,
        context.ddl_sha256, context.semantic_sha256, sha256_context(rendered),
    )
