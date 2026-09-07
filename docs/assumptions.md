# Phase 0 Assumptions & Blockers

## Assumptions

1. **Python 3.12** — target runtime. All type hints use 3.12 syntax (`str | None` instead of `Optional[str]`).
2. **Pydantic v2** — `model_json_schema()` used for JSON Schema export (not v1 `.schema()`).
3. **PostgreSQL with JSONB** — migration uses `postgresql.JSONB` and `postgresql.ARRAY`. Not compatible with SQLite.
4. **Alembic offline mode** — Phase 0 migrations are syntax-validated only; actual DB apply requires a live PostgreSQL instance.
5. **Confidence weights are provisional** — per spec Section 5.4. Will be updated after Phase 6 calibration data.
6. **`frozen=True` on all schemas** — enforces immutability per coding-style rules. Mutation returns a new object via `model.model_copy(update={...})`.
7. **CI uses GitHub Actions** — spec says "Existing CI system"; adapt `ci.yml` to your actual CI runner as needed.

## Unresolved Blockers

- None for Phase 0.

## Next Phase

**Phase 1 — LLM Gateway**: Claude + Gemini adapters, routing table, cost tracking, circuit breaker.
Gate G1 must pass before Phase 2 begins.
