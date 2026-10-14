"""Deterministic governed-vocabulary resolution before generation (FR-3/FR-7).

This is a single-turn metadata transformation. It performs no SQL/model calls.
Global ambiguity is decided before role projection, so hiding one meaning never
causes the resolver to silently pick another. Public wording and alternatives
contain only static questions and names from definitions permitted to the role.
"""

from __future__ import annotations

import re
import unicodedata

from ..contracts import Clarification
from ..db.catalog import SchemaSnapshot
from ..errors import InvalidRequestError
from ..policy.loader import PolicyMatrix
from .contracts import ResolutionStatus, VocabularyResolution
from .entitlements import filter_catalog_for_role
from .models import SemanticCatalog


_SAFE_QUESTION = "Please state the business meaning and time basis you want using the available vocabulary."


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("_", " ").split())


def _lexicon(catalog: SemanticCatalog) -> dict[str, frozenset[str]]:
    targets: dict[str, set[str]] = {}
    for definition in tuple(catalog.entities.values()) + tuple(catalog.metrics.values()):
        for label in (definition.id, definition.name) + definition.aliases:
            targets.setdefault(_normalize(label), set()).add(definition.id)
    for ambiguity in catalog.ambiguities:
        targets.setdefault(_normalize(ambiguity.term), set()).update(ambiguity.targets)
    return {label: frozenset(values) for label, values in targets.items()}


def _clarification(
    candidates: set[str], visible: SemanticCatalog
) -> VocabularyResolution:
    definitions = dict(visible.entities) | dict(visible.metrics)
    options = tuple(sorted({definitions[item].name for item in candidates if item in definitions}))
    return VocabularyResolution(
        status=ResolutionStatus.CLARIFICATION_REQUIRED,
        concept_ids=(),
        clarification=Clarification(question=_SAFE_QUESTION, options=options),
    )


def _finish_term(
    targets: frozenset[str], visible: SemanticCatalog
) -> VocabularyResolution:
    visible_ids = set(visible.entities) | set(visible.metrics)
    if len(targets) != 1 or not targets <= visible_ids:
        return _clarification(set(targets), visible)
    return VocabularyResolution(
        status=ResolutionStatus.RESOLVED,
        concept_ids=tuple(sorted(targets)),
        clarification=None,
    )


def _finish_question(
    matched: tuple[frozenset[str], ...], visible: SemanticCatalog
) -> VocabularyResolution:
    visible_ids = set(visible.entities) | set(visible.metrics)
    # Trigger clarification only on genuine multi-target lexical ambiguity (len(targets) > 1).
    # Unambiguous out-of-entitlement concepts proceed to the model/validator/database layers.
    ambiguous = [targets for targets in matched if len(targets) > 1]
    if ambiguous:
        ambiguous_candidates = set().union(*ambiguous)
        return _clarification(ambiguous_candidates, visible)
    resolved_visible = set().union(*(targets for targets in matched if targets <= visible_ids)) if matched else set()
    return VocabularyResolution(
        status=ResolutionStatus.RESOLVED,
        concept_ids=tuple(sorted(resolved_visible)),
        clarification=None,
    )


def resolve_term(
    term: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
) -> VocabularyResolution:
    """Resolve one explicitly requested business term, or request clarification.

    Unknown, unavailable or globally ambiguous terms receive the same static
    question. The question never repeats a hidden name or exposes whether an
    unavailable object exists. Engineering has its unique governed DIVISION
    meaning; it cannot be inferred to be a department by convenience.
    """
    if not isinstance(term, str) or not term.strip():
        raise InvalidRequestError("An explicit governed term must be nonempty text.")
    visible = filter_catalog_for_role(catalog, matrix, snapshot, business_role)
    targets = _lexicon(catalog).get(_normalize(term))
    if targets is None:
        return _clarification(set(), visible)
    return _finish_term(targets, visible)


def resolve_question(
    question: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
) -> VocabularyResolution:
    """Resolve recognized vocabulary using longest whole-phrase matches.

    An explicit unique phrase such as active headcount covers its shorter
    headcount substring; a separate headcount occurrence remains ambiguous.
    The original question is never rewritten. Words outside governed vocabulary
    remain for the later generator: RESOLVED with no concept IDs asserts no
    business interpretation. Call resolve_term for an explicitly requested term
    that must have a documented meaning; an unknown term then fails closed.
    """
    if not isinstance(question, str) or not question.strip():
        raise InvalidRequestError("Governed resolution requires a nonempty business question.")
    visible = filter_catalog_for_role(catalog, matrix, snapshot, business_role)
    lexicon = _lexicon(catalog)
    normalized = _normalize(question)
    occurrences = []
    for label in sorted(lexicon):
        expression = re.compile(r"(?<!\w)" + re.escape(label) + r"(?!\w)")
        for match in expression.finditer(normalized):
            occurrences.append((match.start(), match.end(), label))
    accepted = []
    # Length first prevents generic inner aliases from overriding an explicit
    # governed phrase; remaining ties use position and lexical order.
    for start, end, label in sorted(occurrences, key=lambda item: (-(item[1] - item[0]), item[0], item[2])):
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in accepted):
            continue
        accepted.append((start, end, label))
    matched = tuple(lexicon[label] for _, _, label in sorted(accepted))
    return _finish_question(matched, visible)
