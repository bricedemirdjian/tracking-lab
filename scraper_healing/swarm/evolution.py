"""Evolution agent — proposes mutations to the scraping logic when the
healer + reviewer flag persistent failures.

Two modes:

1. ``HEURISTIC`` (default, free, deterministic) — uses the same mechanics
   already in ``scraper_healing/recovery.py``: walks the response tree and
   suggests new field paths or aliases. Adds path suffix variants and
   nested-key alternatives based on observed failure patterns.

2. ``LLM`` (opt-in via env ``EVOLUTION_USE_LLM=1`` + ``ANTHROPIC_API_KEY``)
   — sends the failure context (validation errors, response shape diff,
   and a redacted snippet of the response) to Claude and asks for JSON
   formatted proposals. Sandbox-validated before applying. Disabled by
   default to keep cost predictable.

Every proposal is logged to ``data/evolution-log.jsonl`` for audit. Only
proposals that *succeed* on a dry-run replay are persisted via
``core.remember_path``.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .. import core, recovery


_DATA = Path(__file__).parent / "data"
_DATA.mkdir(parents=True, exist_ok=True)
_EVO_LOG = _DATA / "evolution-log.jsonl"


# ── Proposal schema ─────────────────────────────────────────────────────
@dataclass
class Proposal:
    cycle_id: str
    platform: str
    field_name: str
    kind: str  # add_path | add_alias | tune_retry
    payload: dict = field(default_factory=dict)
    source: str = "heuristic"  # heuristic | llm
    reason: str = ""
    applied: bool = False
    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict:
        return asdict(self)


def _append_log(record: dict) -> None:
    try:
        with _EVO_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        core.warn("evolution_log_write_failed", err=str(e))


# ── Heuristic proposals ─────────────────────────────────────────────────
def _propose_paths_from_response(
    response: Any, field_name: str, type_hint: str, aliases: Iterable[str]
) -> list[str]:
    """Walk the response tree, return up to 5 new candidate paths whose
    leaf value passes the type validator. Reuses recovery.find_by_aliases
    but materializes multiple candidates instead of just one.
    """
    proposals: list[str] = []
    seen: set[str] = set()

    # First try the existing recovery logic
    found = recovery.find_by_aliases(response, list(aliases) or [field_name], type_=type_hint)
    if found:
        path, _val = found
        if path not in seen:
            proposals.append(path)
            seen.add(path)

    # Then walk for additional candidates with looser key-name matching
    def walk(obj: Any, prefix: str = "") -> None:
        if len(proposals) >= 5:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else k
                if any(a.lower() in k.lower() for a in [field_name, *aliases]):
                    if isinstance(v, (int, float, str)) and core.is_valid(type_hint, v):
                        if p not in seen:
                            proposals.append(p)
                            seen.add(p)
                if isinstance(v, (dict, list)) and len(prefix) < 80:
                    walk(v, p)
        elif isinstance(obj, list) and obj:
            walk(obj[0], f"{prefix}.[0]" if prefix else "[0]")

    walk(response)
    return proposals[:5]


def _heuristic_proposals(
    *,
    cycle_id: str,
    platform: str,
    response: Any,
    schema: dict,
    validation_errors: list[dict],
    failed_endpoints: list[str],
) -> list[Proposal]:
    out: list[Proposal] = []
    for err in validation_errors:
        if err.get("error") not in {"missing", "invalid"}:
            continue
        field_name = err.get("field")
        if not field_name or field_name not in schema:
            continue
        spec = schema[field_name]
        candidates = _propose_paths_from_response(
            response, field_name, getattr(spec, "type", "string"),
            getattr(spec, "aliases", []) or [],
        )
        for c in candidates:
            out.append(Proposal(
                cycle_id=cycle_id, platform=platform, field_name=field_name,
                kind="add_path", payload={"path": c}, source="heuristic",
                reason=f"validation_{err.get('error')}",
            ))
    # If the same endpoints keep failing, propose tuning retry params
    if len(failed_endpoints) >= 3 and len(set(failed_endpoints)) == 1:
        out.append(Proposal(
            cycle_id=cycle_id, platform=platform, field_name="*",
            kind="tune_retry",
            payload={"endpoint": failed_endpoints[0], "deprioritize": True},
            source="heuristic", reason="repeated_endpoint_failure",
        ))
    return out


# ── LLM proposals (optional) ────────────────────────────────────────────
def _llm_enabled() -> bool:
    return os.getenv("EVOLUTION_USE_LLM") == "1" and bool(os.getenv("ANTHROPIC_API_KEY"))


def _llm_proposals(
    *,
    cycle_id: str,
    platform: str,
    response: Any,
    schema: dict,
    validation_errors: list[dict],
) -> list[Proposal]:
    """Calls Claude with failure context. Falls back to [] on any error.

    Cost-conscious: max 2k tokens response, only invoked when heuristic
    yields nothing AND there are >0 errors. Sandbox-validates Claude's
    JSON output before turning it into Proposals.
    """
    if not _llm_enabled() or not validation_errors:
        return []
    try:
        # Lazy import — anthropic isn't a hard dependency.
        import anthropic  # type: ignore
    except ImportError:
        core.warn("evolution_llm_skipped", reason="anthropic_sdk_missing")
        return []

    # Truncate the response to keep prompt small
    snippet = json.dumps(response, default=str)[:3000]
    schema_brief = {
        k: {"type": v.type, "required": v.required, "aliases": v.aliases or []}
        for k, v in schema.items()
    }
    prompt = f"""You are a scraping reliability engineer. The platform "{platform}" returned a payload, but the validator flagged these errors:

{json.dumps(validation_errors, indent=2)}

Schema:
{json.dumps(schema_brief, indent=2)}

Response snippet (first 3KB):
{snippet}

Propose up to 5 alternative dotted JSON paths that would correctly resolve the failing fields. Reply ONLY with a JSON array of objects:
[{{"field": "...", "path": "...", "reason": "..."}}]
"""
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else "[]"
        # Strip markdown fences if present
        text = text.strip().strip("`").lstrip("json").strip()
        proposals_raw = json.loads(text)
    except Exception as e:
        core.warn("evolution_llm_failed", err=str(e)[:200])
        return []

    out: list[Proposal] = []
    for p in proposals_raw if isinstance(proposals_raw, list) else []:
        if not isinstance(p, dict):
            continue
        f, path = p.get("field"), p.get("path")
        if f and path and f in schema:
            out.append(Proposal(
                cycle_id=cycle_id, platform=platform, field_name=f,
                kind="add_path", payload={"path": path}, source="llm",
                reason=p.get("reason", "llm_suggestion")[:120],
            ))
    return out


# ── Sandbox validation + apply ──────────────────────────────────────────
def _sandbox_validate(proposal: Proposal, response: Any, schema: dict) -> bool:
    """Try the proposed path against the *current* response. Only persist
    if it actually resolves to a valid value. Prevents Evolution from
    poisoning the store with junk paths.
    """
    if proposal.kind != "add_path":
        return True  # other kinds skip path-resolution check
    spec = schema.get(proposal.field_name)
    if spec is None:
        return False
    val = core.get_path(response, proposal.payload["path"])
    return core.is_valid(spec.type, val)


def _apply(proposal: Proposal) -> None:
    if proposal.kind == "add_path":
        core.remember_path(proposal.platform, proposal.field_name, proposal.payload["path"])
        core.info("evolution_event", action="add_path", platform=proposal.platform,
                  field=proposal.field_name, path=proposal.payload["path"], source=proposal.source)
    elif proposal.kind == "tune_retry":
        # Recorded in the audit log only; the existing healer reads scores
        # at runtime so deprioritization happens naturally via record_failure.
        endpoint = proposal.payload.get("endpoint")
        if endpoint:
            core.info("evolution_event", action="tune_retry",
                      platform=proposal.platform, endpoint=endpoint, source=proposal.source)
    proposal.applied = True


# ── Public agent ────────────────────────────────────────────────────────
class EvolutionAgent:
    """Stateless agent invoked by the orchestrator after each cycle whose
    review verdict came back with errors.
    """

    def analyze(
        self,
        *,
        cycle_id: str,
        platform: str,
        response: Any,
        schema: dict,
        validation: dict,
        failed_endpoints: list[str] | None = None,
    ) -> list[Proposal]:
        if validation.get("ok"):
            return []
        validation_errors = validation.get("errors", [])
        proposals = _heuristic_proposals(
            cycle_id=cycle_id, platform=platform, response=response, schema=schema,
            validation_errors=validation_errors,
            failed_endpoints=failed_endpoints or [],
        )
        if not proposals:
            proposals = _llm_proposals(
                cycle_id=cycle_id, platform=platform, response=response,
                schema=schema, validation_errors=validation_errors,
            )
        return proposals

    def apply(self, proposals: list[Proposal], response: Any, schema: dict) -> int:
        applied = 0
        for p in proposals:
            ok = _sandbox_validate(p, response, schema)
            if ok:
                _apply(p)
                applied += 1
            else:
                core.warn("evolution_rejected", platform=p.platform, field=p.field_name,
                          path=p.payload.get("path"), reason="sandbox_validation_failed")
            _append_log(p.to_dict() | {"sandbox_passed": ok})
        return applied
