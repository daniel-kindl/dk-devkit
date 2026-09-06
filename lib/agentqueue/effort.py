"""Which model runs one task, and why.

One task gets one effort tier: ``lightweight``, ``standard`` or ``hard``. The
tier names the implementer model and the independent reviewer model, and both
are pinned provider model IDs from ``manifests/model-tiers.json``. A family
name such as "Sonnet" is what an operator reads; it is never what a run
resolves to.

The tier is chosen before the implementer starts, from data a human wrote:
the repository policy, the labels on the issue, the title, and the number of
acceptance criteria in the body. No model is called to choose a model, and no
rule reads model output.

Resolution order, first decisive rule wins::

    1. policy pins the tier            effortMode "fixed"
    2. an effort:<tier> label          the human said so on this issue
    3. an escalation signal            security, authority, release, CI, ...
    4. breadth of the acceptance criteria
    5. the ordinary issue taxonomy     documentation, bug, feature, ...
    6. the catalog default

Rules 3 to 6 are then raised, never lowered, by one tier per earlier failed
attempt when the policy asks for it. Rules 1 and 2 are explicit human intent
and no signal moves them.

Every decision carries the rule that decided it and every signal that fired,
so a surprising tier can be traced without reading this file.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MANIFEST_NAME = os.path.join("manifests", "model-tiers.json")

_ACCEPTANCE_ITEM = re.compile(r"^\s*[-*]\s*\[[ xX]\]", re.MULTILINE)


class EffortError(Exception):
    """The catalog or the request is unusable. The coordinator refuses."""


@dataclasses.dataclass(frozen=True)
class Model:
    """One pinned role: the CLI that runs it, and the exact model it runs."""

    agent: str
    family: str
    model: str

    def render(self) -> str:
        return f"{self.family} ({self.model})"

    def as_dict(self) -> Dict[str, str]:
        return {"agent": self.agent, "family": self.family, "model": self.model}


@dataclasses.dataclass(frozen=True)
class Tier:
    id: str
    marker: str
    rank: int
    summary: str
    implementer: Model
    reviewer: Model


@dataclasses.dataclass(frozen=True)
class Decision:
    """The resolved tier for one task, and the evidence behind it."""

    tier: Tier
    rule: str
    signals: Tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.tier.id

    @property
    def marker(self) -> str:
        return self.tier.marker

    @property
    def implementer(self) -> Model:
        return self.tier.implementer

    @property
    def reviewer(self) -> Model:
        return self.tier.reviewer

    def label(self) -> str:
        """The compact marker the stage display shows: ``(S) Sonnet``."""
        return f"({self.tier.marker}) {self.tier.implementer.family}"

    def review_label(self) -> str:
        return f"({self.tier.marker}) {self.tier.reviewer.family}"

    def render(self) -> str:
        return (
            f"{self.tier.marker} {self.tier.id}  "
            f"{self.tier.implementer.family} -> {self.tier.reviewer.family}  "
            f"({self.rule})"
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.id,
            "marker": self.tier.marker,
            "rule": self.rule,
            "signals": list(self.signals),
            "implementer": self.tier.implementer.as_dict(),
            "reviewer": self.tier.reviewer.as_dict(),
        }


# ------------------------------------------------------------------ catalog --


@dataclasses.dataclass(frozen=True)
class Catalog:
    tiers: Tuple[Tier, ...]
    default: str
    escalate_tier: str
    escalate_summary: str
    escalate_labels: Tuple[str, ...]
    escalate_words: Tuple[str, ...]
    by_label: Mapping[str, str]
    acceptance_hard: int
    path: str = ""

    def tier(self, identifier: str) -> Tier:
        for tier in self.tiers:
            if tier.id == identifier:
                return tier
        known = ", ".join(t.id for t in self.tiers)
        raise EffortError(
            f"unknown effort tier: {identifier!r}. The catalog defines {known}."
        )

    def has(self, identifier: str) -> bool:
        return any(tier.id == identifier for tier in self.tiers)

    def higher(self, tier: Tier, steps: int = 1) -> Tier:
        """The tier ``steps`` above this one, and the top tier beyond that."""
        ordered = sorted(self.tiers, key=lambda t: t.rank)
        index = min(ordered.index(tier) + max(steps, 0), len(ordered) - 1)
        return ordered[index]

    def at_least(self, tier: Tier, floor: Tier) -> Tier:
        return floor if floor.rank > tier.rank else tier


def manifest_path(install_root: str) -> str:
    return os.path.join(install_root, MANIFEST_NAME)


def _model(raw: Any, where: str) -> Model:
    if not isinstance(raw, dict):
        raise EffortError(f"{where} must hold an object")
    for key in ("agent", "family", "model"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EffortError(f"{where}.{key} must be a non-empty string")
    return Model(str(raw["agent"]), str(raw["family"]), str(raw["model"]))


def _strings(raw: Any, where: str) -> Tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise EffortError(f"{where} must be an array")
    return tuple(str(item).strip().lower() for item in raw if str(item).strip())


def load(path: str) -> Catalog:
    """Read the catalog, and refuse one that cannot be carried out."""
    if not os.path.isfile(path):
        raise EffortError(f"no model tier catalog at {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except ValueError as exc:
        raise EffortError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise EffortError(f"{path} must hold a JSON object")
    if document.get("version") != 1:
        raise EffortError(f"{path}: the catalog version must be 1")

    raw_tiers = document.get("tiers")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise EffortError(f"{path}: tiers must be a non-empty array")

    tiers: List[Tier] = []
    for index, raw in enumerate(raw_tiers):
        where = f"{path}: tiers[{index}]"
        if not isinstance(raw, dict):
            raise EffortError(f"{where} must hold an object")
        identifier = str(raw.get("id", "")).strip()
        marker = str(raw.get("marker", "")).strip()
        if not identifier:
            raise EffortError(f"{where}.id must be a non-empty string")
        if len(marker) != 1:
            raise EffortError(f"{where}.marker must be exactly one character")
        rank = raw.get("rank")
        if not isinstance(rank, int) or rank < 1:
            raise EffortError(f"{where}.rank must be a whole number of at least 1")
        implementer = _model(raw.get("implementer"), f"{where}.implementer")
        reviewer = _model(raw.get("reviewer"), f"{where}.reviewer")
        # Cross-provider review is the point of the pairing. A model that
        # reviews its own implementation is not an independent review, so the
        # catalog cannot express one.
        if implementer.agent == reviewer.agent:
            raise EffortError(
                f"{where}: the implementer and the reviewer must be different "
                f"providers, and both are {implementer.agent!r}"
            )
        tiers.append(
            Tier(identifier, marker, rank, str(raw.get("summary", "")), implementer, reviewer)
        )

    seen_ids = [tier.id for tier in tiers]
    if len(set(seen_ids)) != len(seen_ids):
        raise EffortError(f"{path}: two tiers share an id")
    seen_ranks = [tier.rank for tier in tiers]
    if len(set(seen_ranks)) != len(seen_ranks):
        raise EffortError(f"{path}: two tiers share a rank")
    seen_markers = [tier.marker for tier in tiers]
    if len(set(seen_markers)) != len(seen_markers):
        raise EffortError(f"{path}: two tiers share a marker")

    default = str(document.get("default", "")).strip()
    if not default:
        raise EffortError(f"{path}: default must name a tier")

    signals = document.get("signals") or {}
    if not isinstance(signals, dict):
        raise EffortError(f"{path}: signals must hold an object")
    escalate = signals.get("escalate") or {}
    if not isinstance(escalate, dict):
        raise EffortError(f"{path}: signals.escalate must hold an object")
    by_label_raw = signals.get("byLabel") or {}
    if not isinstance(by_label_raw, dict):
        raise EffortError(f"{path}: signals.byLabel must hold an object")
    by_label = {
        str(key).strip().lower(): str(value).strip()
        for key, value in by_label_raw.items()
        if not str(key).startswith("$")
    }
    breadth = signals.get("breadth") or {}
    acceptance = (breadth.get("acceptanceCriteria") or {}) if isinstance(breadth, dict) else {}
    acceptance_hard = acceptance.get("hard", 0) if isinstance(acceptance, dict) else 0
    if not isinstance(acceptance_hard, int) or acceptance_hard < 0:
        raise EffortError(
            f"{path}: signals.breadth.acceptanceCriteria.hard must not be negative"
        )

    catalog = Catalog(
        tiers=tuple(sorted(tiers, key=lambda t: t.rank)),
        default=default,
        escalate_tier=str(escalate.get("tier", "")).strip(),
        escalate_summary=str(escalate.get("summary", "an escalation signal")),
        escalate_labels=_strings(escalate.get("labels"), f"{path}: signals.escalate.labels"),
        escalate_words=_strings(escalate.get("words"), f"{path}: signals.escalate.words"),
        by_label=by_label,
        acceptance_hard=int(acceptance_hard),
        path=path,
    )

    # Every tier a rule can name must exist. A rule that names a tier the
    # catalog dropped would otherwise fail on the one issue that triggers it.
    catalog.tier(default)
    if catalog.escalate_tier:
        catalog.tier(catalog.escalate_tier)
    for label, target in sorted(catalog.by_label.items()):
        if not catalog.has(target):
            raise EffortError(
                f"{path}: signals.byLabel[{label!r}] names an unknown tier: {target!r}"
            )
    return catalog


# --------------------------------------------------------------- the rules --


def _word_hits(text: str, words: Sequence[str]) -> List[str]:
    lowered = text.lower()
    return [
        word
        for word in words
        if re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered)
    ]


def acceptance_criteria(body: str) -> int:
    """How many acceptance-criteria items the issue body states."""
    return len(_ACCEPTANCE_ITEM.findall(body or ""))


def label_tier(labels: Sequence[str], prefix: str) -> Optional[str]:
    """The tier an ``effort:<tier>`` label names, if the issue carries one."""
    if not prefix:
        return None
    for label in labels:
        text = str(label).strip()
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix):].strip().lower()
    return None


def resolve(issue, policy, catalog: Catalog, attempt: int = 0) -> Decision:
    """Choose the tier for one issue, and say which rule chose it.

    ``attempt`` is the number of earlier failed attempts on this issue. It
    raises the tier, and it never lowers one.
    """
    labels = tuple(str(item).strip().lower() for item in getattr(issue, "labels", ()) or ())
    title = str(getattr(issue, "title", "") or "")
    body = str(getattr(issue, "body", "") or "")
    signals: List[str] = []

    # 1. The repository pinned the tier. Nothing below can move it.
    if getattr(policy, "effortMode", "auto") == "fixed":
        tier = catalog.tier(policy.effort)
        return Decision(tier, "the repository policy pins the tier", ("policy: fixed",))

    # 2. The human said so on this issue.
    prefix = getattr(policy, "effortLabelPrefix", "effort:")
    named = label_tier(labels, prefix)
    if named:
        if not catalog.has(named):
            raise EffortError(
                f"issue #{getattr(issue, 'number', '?')} carries the label "
                f"{prefix}{named}, and the catalog defines no tier {named!r}"
            )
        return Decision(
            catalog.tier(named), f"the issue carries {prefix}{named}", (f"label: {prefix}{named}",)
        )

    escalation: Optional[Tier] = None
    if catalog.escalate_tier:
        hit_labels = [label for label in labels if label in catalog.escalate_labels]
        hit_words = _word_hits(title, catalog.escalate_words)
        if hit_labels or hit_words:
            escalation = catalog.tier(catalog.escalate_tier)
            for label in hit_labels:
                signals.append(f"escalate label: {label}")
            for word in hit_words:
                signals.append(f"escalate word: {word}")

    criteria = acceptance_criteria(body)
    breadth: Optional[Tier] = None
    if catalog.acceptance_hard and criteria >= catalog.acceptance_hard:
        breadth = catalog.tier("hard") if catalog.has("hard") else None
        if breadth is not None:
            signals.append(f"acceptance criteria: {criteria}")

    taxonomy: Optional[Tier] = None
    taxonomy_label = ""
    for label in labels:
        target = catalog.by_label.get(label)
        if target is None:
            continue
        candidate = catalog.tier(target)
        if taxonomy is None or candidate.rank > taxonomy.rank:
            taxonomy, taxonomy_label = candidate, label

    # 3, 4, 5, 6. The first signal that fired decides, and the rules are
    # ordered by how much the repository trusts them.
    if escalation is not None:
        tier, rule = escalation, catalog.escalate_summary
    elif breadth is not None:
        tier, rule = breadth, f"the issue states {criteria} acceptance criteria"
    elif taxonomy is not None:
        tier, rule = taxonomy, f"the {taxonomy_label} label"
        signals.append(f"taxonomy label: {taxonomy_label}")
    else:
        tier, rule = catalog.tier(catalog.default), "the catalog default"

    # A repeat attempt is evidence that the earlier tier was not enough.
    if attempt > 0 and getattr(policy, "escalateEffortOnRetry", True):
        raised = catalog.higher(tier, attempt)
        if raised.rank > tier.rank:
            signals.append(f"attempt {attempt}")
            tier = raised
            rule = f"{rule}, raised after {attempt} failed attempt" + (
                "s" if attempt > 1 else ""
            )

    return Decision(tier, rule, tuple(signals))
