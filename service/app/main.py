"""
FastAPI entrypoint.

Deliberately stateless for now, per the current phase: DB/auth/
multi-tenancy are on hold, so `/scans` takes a CSV (and optional
related CSVs) straight off the request, runs the existing pipeline
in-memory, and returns the result directly — nothing is persisted,
no scan history, no tenant isolation. That's a real, known limitation
(anyone who can reach this service can run a scan), not an oversight;
it's what makes the frontend/eval work testable against a live HTTP
service right now, ahead of the DB/auth phase which will wrap this
same pipeline logic rather than replace it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent.cross_table_reasoning import (
    CrossTableVerificationLabel,
    CrossTableVerifier,
    resolve_fk_pairs,
    run_cross_table_semantic_with_iteration,
)
from app.agent.cost_estimate import ScanCostEstimate, estimate_scan_cost
from app.agent.generator import GeneratorAgent
from app.domain.confidence import derive_confidence
from app.version import (
    CONFIDENCE_DERIVATION_VERSION,
    CROSS_TABLE_PROMPT_VERSION,
    DETECTION_VERSION,
    SCORING_VERSION,
    SEMANTIC_PROMPT_VERSION,
)
from app.canonical.models import CanonicalTable, ScanContext
from app.checks.referential_integrity import _FK_SUFFIX, _PK_COLUMN, _related_table_name
from app.config import ConfigError, gemini_api_key, groq_api_key
from app.connectors.base import ConnectorConfig
from app.connectors.csv_connector import CSVConnector
from app.scoring.scorer import compute_scorecard

app = FastAPI(title="DBCaaS Python Service")

# Wide open for local dev (Next.js on :3000) — this needs to be locked
# down to real allowed origins once this is ever deployed, same
# tracked gap as auth: nothing here enforces who can call this yet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _table_from_upload(upload: UploadFile, tenant_id: str, source_id: str) -> CanonicalTable:
    """Writes the upload to a temp file so the existing CSVConnector
    (which is file-path-based) can be reused as-is rather than forked
    into an in-memory variant. The connector's own filename-derived
    table_name would be the random temp-file name, though, which
    would silently break the referential-integrity name heuristic
    (an "accounts.csv" upload needs table_name == "accounts") — so
    it's overridden afterward from the ORIGINAL uploaded filename."""
    content = upload.file.read()
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        config = ConnectorConfig(
            tenant_id=tenant_id, source_id=source_id, settings={"file_path": tmp_path}
        )
        table = CSVConnector(config).extract()[0]
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    table.table_name = Path(upload.filename or "table").stem
    return table


# Custom instructions are meant to be a sentence or two of plain English
# ("flag anything that seems off for this industry"), not an essay — the
# compiler prompt and the semantic-reasoning prompt both inline this text
# verbatim, so an unbounded upload could blow up prompt size/cost. 4000
# chars is generous (roughly 700-800 words) for what this field is for;
# anything longer gets truncated with a warning rather than silently
# dropped or hard-rejected.
_MAX_INSTRUCTION_CHARS = 4000


class InstructionFileError(ValueError):
    """Raised when an uploaded custom-instruction file can't be read as text."""


def _extract_instruction_text(upload: UploadFile) -> str:
    """Reads the full text out of an uploaded .txt or .docx custom-
    instruction file. .txt is a plain decode; .docx needs python-docx
    since the format is a zipped XML bundle, not plain text. Anything
    else is rejected up front rather than passed through and silently
    mis-parsed."""
    filename = upload.filename or "instruction"
    suffix = Path(filename).suffix.lower()
    content = upload.file.read()

    if suffix == ".txt" or suffix == "":
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return content.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise InstructionFileError(
                    f"Couldn't read '{filename}' as text (not valid UTF-8 or Latin-1)."
                ) from exc

    if suffix == ".docx":
        try:
            import docx  # python-docx
        except ImportError as exc:
            raise InstructionFileError(
                "The server is missing the python-docx package needed to read "
                ".docx files — install it or upload a .txt file instead."
            ) from exc

        import io

        try:
            document = docx.Document(io.BytesIO(content))
        except Exception as exc:  # python-docx raises assorted low-level errors on bad files
            raise InstructionFileError(
                f"Couldn't read '{filename}' as a Word document — it may be corrupted "
                "or not actually a .docx file."
            ) from exc

        paragraphs = [p.text for p in document.paragraphs]
        return "\n".join(paragraphs)

    raise InstructionFileError(
        f"Unsupported custom-instruction file type '{suffix or '(none)'}' — upload a .txt or .docx file."
    )


class FlaggedRowOut(BaseModel):
    row_index: int
    row_data: dict
    deterministic_reasons: list[str]
    semantic_reason: str | None = None
    semantic_confidence: float | None = None
    verification_label: str | None = None
    verification_notes: str | None = None
    # A second, independently-derived confidence figure for the
    # semantic flag, alongside the raw self-reported one above — see
    # app/domain/confidence.py for why the raw number alone isn't
    # trustworthy as a probability. None when there's no semantic flag
    # on this row at all (nothing to derive it from).
    derived_confidence: float | None = None


class SecurityFinding(BaseModel):
    """A row the deterministic prompt-injection backstop
    (app.checks.injection_detection) flagged as looking like a hostile
    payload — a SEPARATE bucket from quality findings on purpose: it
    never contributes to any metric score (see scorer.py's exclusion
    of this check_name). It is NOT a substitute for flagged_rows —
    the same row still appears there too (see ScanResponse.flagged_rows'
    own note below), so this list is additive detail for a future
    security-alerts UI, not the only place the row shows up.

    `severity` is "high" or "low" (see injection_detection.py's
    two-tier design): "high" means the row was also QUARANTINED —
    excluded from semantic reasoning entirely, real containment, not
    just a label (see quarantined_row_count below and
    GeneratorAgent.run's containment logic). "low" means the language
    matched is ambiguous, ordinary-sounding business phrasing
    ("pre-approved", "compliance team") — reported for visibility, but
    the row was NOT excluded from semantic review over it alone.
    Frontend surfacing of this list is a follow-up ticket — this field
    exists so the execution layer is functionally secure first."""

    row_index: int
    row_data: dict
    matched_columns: list[str]
    detail: str
    severity: str  # "high" (quarantined) | "low" (reported only)


class ScanResponse(BaseModel):
    table_name: str
    total_rows: int
    overall_score: float
    metric_scores: list[dict]
    # Includes rows the prompt-injection backstop flagged (both
    # severity tiers) — a row's problem being a security one rather
    # than a quality one is never a reason for it to vanish from the
    # human-facing review list. deterministic_reasons on such a row is
    # prefixed "SECURITY (...)" so it's distinguishable at a glance;
    # see security_findings below for the structured version of the
    # same fact (matched columns, severity) meant for a future
    # dedicated UI.
    flagged_rows: list[FlaggedRowOut]
    semantic_iterations: int
    llm_used: bool
    compilation: dict | None = None
    warnings: list[str] = []
    # Which prompt/scoring logic produced this scorecard — see
    # app/version.py. Answers "why did this score change after an
    # evaluation-logic change?" without needing any persistence layer;
    # the version travels with the response itself.
    versions: dict[str, str] = {}
    # Prompt-injection findings (the "Quarantine Model") — kept as
    # explicit fields rather than something the client must infer from
    # total_rows vs. semantic_iterations' coverage. Includes BOTH
    # severity tiers (see SecurityFinding.severity); quarantined_row_count
    # below counts only the "high" subset, since that's the only one
    # actually excluded from semantic reasoning.
    security_findings: list[SecurityFinding] = []
    # How many of total_rows were QUARANTINED (high-confidence match —
    # see injection_detection.py) and therefore never reasoned over by
    # the semantic layer and never scored under any quality metric. A
    # low-confidence-only match is NOT counted here, since that row
    # stays fully eligible for normal semantic review.
    quarantined_row_count: int = 0
    # The actual denominator the semantic layer reasoned over this
    # scan: total_rows - quarantined_row_count. Exposed explicitly, the
    # same "never make the caller derive a fact" convention as
    # derived_confidence above and semantic_coverage_warning below —
    # so a client sees directly why rows_evaluated (semantic_iterations'
    # coverage) doesn't match total_rows, rather than having to notice
    # security_findings exists and subtract its length itself.
    semantic_rows_considered: int = 0


def _resolve_custom_instruction(
    custom_instruction: str | None,
    custom_instruction_file: UploadFile | None,
    warnings: list[str],
) -> str | None:
    """Shared precedence logic for /scans and /scans/schema: an uploaded
    instruction file wins over typed text when both are somehow present,
    with the truncation/empty/unsupported-type checks applied either way."""
    if custom_instruction_file is None or not custom_instruction_file.filename:
        return custom_instruction

    if custom_instruction and custom_instruction.strip():
        warnings.append(
            "Both a typed custom instruction and an instruction file were provided — "
            "the file was used and the typed text was ignored."
        )
    try:
        extracted = _extract_instruction_text(custom_instruction_file)
    except InstructionFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    extracted = extracted.strip()
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail=f"'{custom_instruction_file.filename}' didn't contain any readable text.",
        )
    if len(extracted) > _MAX_INSTRUCTION_CHARS:
        warnings.append(
            f"The uploaded instruction file was {len(extracted)} characters — truncated to "
            f"the first {_MAX_INSTRUCTION_CHARS} characters."
        )
        extracted = extracted[:_MAX_INSTRUCTION_CHARS]
    return extracted


def _current_versions(llm, verifier_llm) -> dict[str, str]:
    """Duck-typed on `_model` (both GroqClient and GeminiClient carry
    it) rather than importing those classes here, so this stays
    agnostic to which concrete client was configured. Model identifiers
    are omitted entirely when no LLM is configured, rather than showing
    a misleading "no model" placeholder — llm_used already says that
    clearly elsewhere in the response."""
    versions = {
        "detection_version": DETECTION_VERSION,
        "scoring_version": SCORING_VERSION,
        "confidence_derivation_version": CONFIDENCE_DERIVATION_VERSION,
    }
    if llm is not None:
        versions["semantic_prompt_version"] = SEMANTIC_PROMPT_VERSION
        versions["cross_table_prompt_version"] = CROSS_TABLE_PROMPT_VERSION
        model = getattr(llm, "_model", None)
        if model:
            versions["generator_model"] = model
    if verifier_llm is not None:
        verifier_model = getattr(verifier_llm, "_model", None)
        if verifier_model:
            versions["verifier_model"] = verifier_model
    return versions


def _run_table_scan(
    table: CanonicalTable,
    context: ScanContext | None,
    *,
    llm,
    verifier_llm,
    custom_instruction: str | None,
    max_semantic_llm_calls: int | None,
) -> tuple[ScanResponse, object]:
    """Runs the full detection pipeline for ONE table and shapes the
    result into a ScanResponse. Shared by /scans (a single table, no
    schema context) and /scans/schema (N tables, each scanned against
    the same shared context so referential-integrity checks can see
    every other uploaded table). Returns the response alongside the raw
    GeneratorAgent result, since /scans/schema needs the raw
    check_results afterward to extract cross-table findings — reshaping
    that out of the already-built ScanResponse would mean re-parsing
    the human-readable `detail` strings instead of using the structured
    data that's already sitting right there.
    """
    result = GeneratorAgent().run(
        table,
        context,
        llm=llm,
        custom_instruction=custom_instruction,
        verifier_llm=verifier_llm,
        max_semantic_llm_calls=max_semantic_llm_calls,
    )
    scorecard = compute_scorecard(result, table)

    warnings: list[str] = []
    if result.semantic_coverage_warning:
        warnings.append(result.semantic_coverage_warning)

    not_evaluated = [m.metric.value for m in scorecard.metric_scores if not m.evaluated]
    if not_evaluated:
        warnings.append(
            f"Not evaluated this scan (no applicable check ran): {', '.join(not_evaluated)}. "
            f"These are excluded from overall_score, not counted as 100."
        )

    quarantined_row_count = len(result.quarantined_row_indices)
    if quarantined_row_count > 0:
        warnings.append(
            f"{quarantined_row_count} row(s) were quarantined as a security threat "
            f"(high-confidence prompt-injection payload detected) — see "
            f"security_findings. These rows are excluded from every quality metric "
            f"and were never sent to an LLM prompt; semantic_rows_considered "
            f"reflects the reduced coverage this causes."
        )

    injection_check_result = next(
        (r for r in result.check_results if r.check_name == "prompt_injection_check"), None
    )
    security_findings: list[SecurityFinding] = []
    if injection_check_result is not None:
        # Both severity tiers are reported here — not just the
        # quarantined subset — so a low-confidence match (still a real
        # signal worth a human's attention) isn't invisible just
        # because it didn't clear the bar for containment.
        for idx in injection_check_result.flagged_row_indices:
            severity = injection_check_result.row_severity.get(idx, "high")
            security_findings.append(
                SecurityFinding(
                    row_index=idx,
                    row_data=table.rows[idx] if idx < len(table.rows) else {},
                    matched_columns=injection_check_result.flagged_fields.get(idx, []),
                    detail=injection_check_result.detail,
                    severity=severity,
                )
            )

    det_reasons_by_row: dict[int, list[str]] = {}
    for check_result in result.check_results:
        for idx in check_result.flagged_row_indices:
            if check_result.check_name == "prompt_injection_check":
                # Distinctly labeled rather than skipped — see
                # FlaggedRowOut/ScanResponse.flagged_rows' own note:
                # a row must stay visible in the ordinary review list
                # even when its problem is a security one.
                severity = check_result.row_severity.get(idx, "high")
                det_reasons_by_row.setdefault(idx, []).append(
                    f"SECURITY ({severity}-confidence prompt-injection match): {check_result.detail}"
                )
            else:
                det_reasons_by_row.setdefault(idx, []).append(
                    f"{check_result.check_name}: {check_result.detail}"
                )

    semantic_by_row = {f.row_index: f for f in result.semantic_flags}
    verified_by_row = {v.row_index: v for v in result.verified_flags}

    flagged_rows: list[FlaggedRowOut] = []
    for idx in result.flagged_row_indices:
        sem = semantic_by_row.get(idx)
        ver = verified_by_row.get(idx)
        flagged_rows.append(
            FlaggedRowOut(
                row_index=idx,
                row_data=table.rows[idx] if idx < len(table.rows) else {},
                deterministic_reasons=det_reasons_by_row.get(idx, []),
                semantic_reason=sem.reason if sem else None,
                semantic_confidence=sem.confidence if sem else None,
                verification_label=ver.label.value if ver else None,
                verification_notes=ver.verifier_notes if ver else None,
                derived_confidence=(
                    derive_confidence(
                        "semantic_single_table",
                        ver.label.value if ver else None,
                        ver.verification_failed if ver else False,
                    )
                    if sem
                    else None
                ),
            )
        )

    response = ScanResponse(
        table_name=table.table_name,
        total_rows=len(table.rows),
        overall_score=scorecard.overall_score,
        metric_scores=[m.model_dump() for m in scorecard.metric_scores],
        flagged_rows=flagged_rows,
        semantic_iterations=result.semantic_iterations,
        llm_used=llm is not None,
        compilation=result.compilation.model_dump() if result.compilation else None,
        warnings=warnings,
        versions=_current_versions(llm, verifier_llm),
        security_findings=security_findings,
        quarantined_row_count=quarantined_row_count,
        semantic_rows_considered=len(table.rows) - quarantined_row_count,
    )
    return response, result


def _configure_llms(warnings: list[str]) -> tuple[object | None, object | None]:
    """Wires up Groq/Gemini clients if both API keys are configured,
    else returns (None, None) with an explanatory warning appended —
    shared by /scans and /scans/schema so the "no keys configured"
    behavior stays identical between them."""
    try:
        groq_api_key()
        gemini_api_key()
        from app.agent.llm_clients import GeminiClient, GroqClient

        return GroqClient(), GeminiClient()
    except ConfigError:
        warnings.append(
            "GROQ_API_KEY/GEMINI_API_KEY not set on the server — ran deterministic "
            "checks only. Semantic reasoning, verification, and custom instructions "
            "all need an LLM and were skipped."
        )
        return None, None


class ScanEstimateResponse(BaseModel):
    tables: list[ScanCostEstimate]
    total_estimated_llm_calls: int
    total_estimated_cost_usd: float
    llm_configured: bool
    warnings: list[str] = []


@app.post("/scans/estimate", response_model=ScanEstimateResponse)
async def estimate_scan(
    files: list[UploadFile] = File(...),
    max_semantic_llm_calls: int | None = Form(default=None),
) -> ScanEstimateResponse:
    """Pure arithmetic, no LLM calls — shows the user what a scan
    WOULD cost before they commit to running one. Works for a single
    file (the same shape /scans takes) or multiple (the same shape
    /scans/schema takes); this endpoint doesn't care which, since the
    estimate is per-table either way. Returns a real, non-zero
    llm_configured=False signal rather than silently estimating calls
    that would actually be skipped — an estimate should never claim
    coverage the server can't actually deliver."""
    warnings: list[str] = []
    tables = [
        _table_from_upload(f, tenant_id="api", source_id="api") for f in files if f.filename
    ]
    if not tables:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    try:
        groq_api_key()
        gemini_api_key()
        llm_configured = True
    except ConfigError:
        llm_configured = False
        warnings.append(
            "GROQ_API_KEY/GEMINI_API_KEY not set on the server — semantic reasoning "
            "would be skipped entirely, so the real scan would cost 0 LLM calls "
            "regardless of the estimate below."
        )

    estimates = [estimate_scan_cost(t, max_llm_calls=max_semantic_llm_calls) for t in tables]
    return ScanEstimateResponse(
        tables=estimates,
        total_estimated_llm_calls=sum(e.estimated_llm_calls for e in estimates) if llm_configured else 0,
        total_estimated_cost_usd=round(sum(e.estimated_cost_usd for e in estimates), 4) if llm_configured else 0.0,
        llm_configured=llm_configured,
        warnings=warnings,
    )


@app.post("/scans", response_model=ScanResponse)
async def run_scan(
    file: UploadFile = File(...),
    related_files: list[UploadFile] | None = File(default=None),
    custom_instruction: str | None = Form(default=None),
    custom_instruction_file: UploadFile | None = File(default=None),
    max_semantic_llm_calls: int | None = Form(default=None),
) -> ScanResponse:
    warnings: list[str] = []
    custom_instruction = _resolve_custom_instruction(custom_instruction, custom_instruction_file, warnings)

    table = _table_from_upload(file, tenant_id="api", source_id="api")
    related_tables = [
        _table_from_upload(f, tenant_id="api", source_id="api")
        for f in (related_files or [])
        if f.filename
    ]
    context = ScanContext(tables=[table, *related_tables]) if related_tables else None

    llm, verifier_llm = _configure_llms(warnings)
    if llm is None:
        custom_instruction = None  # nothing can compile or reason over it without an LLM

    response, _result = _run_table_scan(
        table,
        context,
        llm=llm,
        verifier_llm=verifier_llm,
        custom_instruction=custom_instruction,
        max_semantic_llm_calls=max_semantic_llm_calls,
    )
    response.warnings = warnings + response.warnings
    return response


class CrossTableFinding(BaseModel):
    """A referential-integrity problem that genuinely spans two tables
    (as opposed to the check's own "fallback mode", which just flags
    blank FK-shaped values with nothing to verify them against — that
    case stays inside the owning table's own warnings, not here, since
    it isn't actually a cross-table fact). from_table is the table that
    holds the foreign key; to_table is the table it's supposed to
    reference."""

    from_table: str
    from_column: str
    to_table: str
    flagged_row_count: int


class CrossTableSemanticFinding(BaseModel):
    """A CONTENT-level inconsistency between a child row and the parent
    row its foreign key already resolves to — e.g. the child's company
    name doesn't match the parent account's name. Distinct from
    CrossTableFinding above, which is a structural fact (the FK doesn't
    resolve at all); this only ever runs on pairs that DID resolve,
    since an unresolved pair has nothing meaningful to compare content
    against. Requires an LLM — empty whenever one isn't configured."""

    from_table: str
    from_row_index: int
    to_table: str
    to_row_index: int
    fk_column: str
    reason: str
    confidence: float
    verification_label: str | None = None
    verification_notes: str | None = None
    # See FlaggedRowOut.derived_confidence — same idea, cross-table
    # variant (a lower base rate — see app/domain/confidence.py).
    derived_confidence: float | None = None


class SchemaScanResponse(BaseModel):
    tables: list[ScanResponse]
    cross_table_findings: list[CrossTableFinding]
    cross_table_semantic_findings: list[CrossTableSemanticFinding] = []
    # Row-count-weighted mean of each table's overall_score, so a
    # 5-row lookup table with a bad score doesn't drag the schema-wide
    # number down as much as a 5,000-row table with the same score —
    # a straight unweighted average would treat those as equally
    # important, which misrepresents how much of the actual data is
    # affected.
    aggregate_score: float
    total_tables: int
    total_rows: int
    llm_used: bool
    warnings: list[str] = []
    # Schema-wide echo of the same versions every per-table ScanResponse
    # already carries (see ScanResponse.versions) — duplicated at this
    # level too since aggregate_score and cross_table_findings are
    # schema-wide facts that deserve their own version trace without
    # requiring a caller to dig into tables[0].versions to find it.
    versions: dict[str, str] = {}


def _extract_cross_table_findings(
    table: CanonicalTable, context: ScanContext, result
) -> list[CrossTableFinding]:
    """Reads the referential_integrity_check's structured flagged_fields
    (row_index -> [column names]) rather than parsing its human-readable
    `detail` string, so this doesn't break if that string's wording ever
    changes. Only counts a column as a genuine cross-table finding when
    the related table it names was actually present in this scan's
    context — a bare blank-FK flag with no related table to check
    against (the check's own "fallback mode") isn't a cross-table fact
    and is left for that table's own deterministic warnings instead."""
    check_result = next(
        (r for r in result.check_results if r.check_name == "referential_integrity_check"), None
    )
    if check_result is None:
        return []

    fk_columns = [
        name
        for name in table.column_names()
        if name.endswith(_FK_SUFFIX) and name != _PK_COLUMN
    ]

    findings: list[CrossTableFinding] = []
    for fk_col in fk_columns:
        related_name = _related_table_name(fk_col)
        if context.get_table(related_name) is None:
            continue  # fallback mode — no related table, nothing cross-table to report
        count = sum(1 for cols in check_result.flagged_fields.values() if fk_col in cols)
        if count > 0:
            findings.append(
                CrossTableFinding(
                    from_table=table.table_name,
                    from_column=fk_col,
                    to_table=related_name,
                    flagged_row_count=count,
                )
            )
    return findings


def _find_fk_relationships(
    tables: list[CanonicalTable], context: ScanContext
) -> list[tuple[CanonicalTable, CanonicalTable, str]]:
    """Every (child_table, parent_table, fk_column) triple where the
    parent table named by the FK-suffix heuristic is actually present
    in this scan — the same relationships _extract_cross_table_findings
    reports structurally, surfaced here as table objects instead of
    counts so the cross-table semantic pass knows exactly which table
    pairs to reason over."""
    relationships: list[tuple[CanonicalTable, CanonicalTable, str]] = []
    for table in tables:
        fk_columns = [
            name for name in table.column_names() if name.endswith(_FK_SUFFIX) and name != _PK_COLUMN
        ]
        for fk_col in fk_columns:
            related_name = _related_table_name(fk_col)
            parent = context.get_table(related_name)
            if parent is not None:
                relationships.append((table, parent, fk_col))
    return relationships


@app.post("/scans/schema", response_model=SchemaScanResponse)
async def run_schema_scan(
    files: list[UploadFile] = File(...),
    # JSON object mapping table_name (the uploaded file's stem, same
    # convention as the single-table /scans endpoint) to a plain-English
    # instruction for THAT table only — e.g. {"leads": "flag anything
    # that seems off for this industry"}. Deliberately per-table, not
    # cross-table: an instruction like "flag leads without a matching
    # account" would need the server to infer which tables and join key
    # it's even talking about, which is schema-relationship inference,
    # not instruction compiling — out of scope here, same as the
    # embedding-based schema-agnostic column matching was deferred
    # earlier. File-upload instructions (.txt/.docx) stay single-table,
    # via /scans, for the same reason: there's no clean per-table
    # multi-file-upload pairing UI yet.
    custom_instructions: str | None = Form(default=None),
    max_semantic_llm_calls: int | None = Form(default=None),
    # Explicit, opt-in cost ceiling on the cross-table semantic pass —
    # same "caller decides, method never silently caps" convention as
    # max_semantic_llm_calls above. None means full coverage of every
    # resolved cross-table pair, same default as everything else here.
    max_cross_table_llm_calls: int | None = Form(default=None),
) -> SchemaScanResponse:
    warnings: list[str] = []

    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="/scans/schema needs at least 2 tables — for a single table, use /scans instead.",
        )

    instructions_map: dict[str, str] = {}
    if custom_instructions:
        import json

        try:
            parsed = json.loads(custom_instructions)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="custom_instructions must be a JSON object mapping table name -> instruction text.",
            ) from exc
        if not isinstance(parsed, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
        ):
            raise HTTPException(
                status_code=400,
                detail="custom_instructions must be a JSON object of {table_name: instruction} string pairs.",
            )
        instructions_map = parsed

    tables = [_table_from_upload(f, tenant_id="api", source_id="api") for f in files if f.filename]
    context = ScanContext(tables=tables)

    unmatched = set(instructions_map) - {t.table_name for t in tables}
    if unmatched:
        warnings.append(
            f"custom_instructions named table(s) not present in this upload, ignored: {', '.join(sorted(unmatched))}"
        )

    llm, verifier_llm = _configure_llms(warnings)

    table_responses: list[ScanResponse] = []
    cross_table_findings: list[CrossTableFinding] = []
    # Each table's quarantined row indices, keyed by table_name — built
    # during the per-table loop below, then used to filter the
    # cross-table semantic pass afterward so a pair touching a
    # quarantined row on EITHER side (child or parent) never reaches an
    # LLM prompt. No changes needed to cross_table_reasoning.py itself:
    # filtering happens entirely here, at the orchestration layer,
    # reusing resolve_fk_pairs/run_cross_table_semantic_with_iteration
    # unmodified.
    quarantined_by_table: dict[str, set[int]] = {}
    for table in tables:
        instruction = instructions_map.get(table.table_name) if llm is not None else None
        response, result = _run_table_scan(
            table,
            context,
            llm=llm,
            verifier_llm=verifier_llm,
            custom_instruction=instruction,
            max_semantic_llm_calls=max_semantic_llm_calls,
        )
        table_responses.append(response)
        cross_table_findings.extend(_extract_cross_table_findings(table, context, result))
        quarantined_by_table[table.table_name] = set(result.quarantined_row_indices)

    # Cross-table SEMANTIC pass — content-level judgment on pairs whose
    # FK already resolves, as opposed to the structural check above
    # (which only ever looks at pairs that DON'T resolve). Only runs
    # with an LLM configured, same gating as every other semantic path
    # in this service; silently produces nothing otherwise, same as a
    # custom_instruction does without an LLM.
    cross_table_semantic_findings: list[CrossTableSemanticFinding] = []
    if llm is not None:
        for child, parent, fk_col in _find_fk_relationships(tables, context):
            pairs = resolve_fk_pairs(child, parent, fk_col)
            child_quarantined = quarantined_by_table.get(child.table_name, set())
            parent_quarantined = quarantined_by_table.get(parent.table_name, set())
            if child_quarantined or parent_quarantined:
                # Containment on the cross-table path too: a pair
                # touching a quarantined row on EITHER side is dropped
                # before it ever reaches the LLM, not merely excluded
                # from scoring afterward. resolve_fk_pairs and
                # run_cross_table_semantic_with_iteration themselves
                # are untouched — this filter is the entire fix.
                pairs = [
                    (c, p)
                    for c, p in pairs
                    if c not in child_quarantined and p not in parent_quarantined
                ]
            if not pairs:
                continue
            flags, _calls, coverage_warning = run_cross_table_semantic_with_iteration(
                child, parent, pairs, llm, max_llm_calls=max_cross_table_llm_calls
            )
            if coverage_warning:
                warnings.append(coverage_warning)
            if not flags:
                continue

            if verifier_llm is not None:
                verified = CrossTableVerifier(verifier_llm).verify(child, parent, flags)
                verified_by_key = {(v.from_row_index, v.to_row_index): v for v in verified}
            else:
                verified_by_key = {}

            for f in flags:
                v = verified_by_key.get((f.from_row_index, f.to_row_index))
                if v is not None and v.label == CrossTableVerificationLabel.REJECTED:
                    continue  # an explicitly rejected claim isn't surfaced as a finding
                cross_table_semantic_findings.append(
                    CrossTableSemanticFinding(
                        from_table=child.table_name,
                        from_row_index=f.from_row_index,
                        to_table=parent.table_name,
                        to_row_index=f.to_row_index,
                        fk_column=fk_col,
                        reason=f.reason,
                        confidence=f.confidence,
                        verification_label=v.label.value if v else None,
                        verification_notes=v.verifier_notes if v else None,
                        derived_confidence=derive_confidence(
                            "semantic_cross_table",
                            v.label.value if v else None,
                            v.verification_failed if v else False,
                        ),
                    )
                )

    total_rows = sum(t.total_rows for t in table_responses)
    aggregate_score = (
        sum(t.overall_score * t.total_rows for t in table_responses) / total_rows
        if total_rows > 0
        else 100.0
    )

    return SchemaScanResponse(
        tables=table_responses,
        cross_table_findings=cross_table_findings,
        cross_table_semantic_findings=cross_table_semantic_findings,
        aggregate_score=round(aggregate_score, 2),
        total_tables=len(table_responses),
        total_rows=total_rows,
        llm_used=llm is not None,
        warnings=warnings,
        versions=_current_versions(llm, verifier_llm),
    )
