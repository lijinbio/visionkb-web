"""A fake visionkb-api (/v1) with canned envelopes: real identifiers, synthetic values. Records every request."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

RELEASE = "visionkb-0000.01.0"
EDGE = "visionkb:e-0123456789abcdef0123456789abcdef01234567"


def env(data, page=None, status=200, error=None, warnings=None):
    body = {"status": "error" if error else "ok", "kg_release": RELEASE, "data": data, "page": page,
            "warnings": warnings or [], "error": error}  # fmt: skip
    return JSONResponse(body, status_code=status)


def make_app(token: str, hits: list | None = None):
    hits = hits if hits is not None else []

    def authed(request: Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {token}"

    def guard(fn, auth=True):
        async def endpoint(request: Request):
            hits.append({"path": request.url.path, "query": request.url.query, "method": request.method,
                         "auth_ok": authed(request)})  # fmt: skip
            if auth and not authed(request):
                return env(None, status=401, error={"code": "unauthorized", "message": "missing or invalid token"})
            return await fn(request)

        return endpoint

    async def health(r):
        return env(
            {"neo4j": {"status": "ok"}, "summaries": {"status": "ok"}, "postgres": {"status": "ok"}, "release": RELEASE}
        )

    async def ready(r):
        return env({"neo4j": {"status": "ok"}, "summaries": {"status": "ok"}, "postgres": {"status": "ok"}})

    async def release(r):
        return env({"kg_release": RELEASE, "biolink_version": "4.4.6", "counts": {"edges_total": 3},
                    "known_issues": [{"id": "KI-1", "title": "cross-lineage marker programs in cell-type groups",
                                      "rod_program_groups": ["visionkb:ds-hrca-snrna|HAC66"], "status": "open"}],
                    "expression_edge_rule_text": "pct_expressing >= 0.1 and n_cells >= 20", "sources": []})  # fmt: skip

    async def search(r):
        q = r.query_params.get("q", "")
        rows = [{"id": "HGNC:10012", "name": "rhodopsin", "category": ["biolink:Gene"], "symbol": "RHO",
                 "synonyms": ["OPN2"], "match": "exact_symbol", "score": 0.99}] if q.upper().startswith("RHO") else []  # fmt: skip
        return env(rows, {"limit": int(r.query_params.get("limit", 20)), "offset": 0, "total": None})

    async def entity(r):
        curie = r.path_params["curie"]
        if curie != "HGNC:10012" and curie != "CL:0000604":
            return env(None, status=404, error={"code": "not_found", "message": f"no node {curie}"})
        return env({"node": {"id": curie, "name": "rhodopsin", "category": ["biolink:Gene"]},
                    "degree_by_predicate": {"biolink:expressed_in": {"out": 1, "in": 0}}})  # fmt: skip

    async def relationships(r):
        row = {"edge_id": EDGE, "subject": {"id": "HGNC:10012", "name": "rhodopsin", "category": ["biolink:Gene"]},
               "predicate": "biolink:expressed_in", "object": {"id": "CL:0000604", "name": "retinal rod cell",
               "category": ["biolink:Cell"]}, "qualifiers": {}, "knowledge_level": "observation",
               "agent_type": "data_analysis_pipeline", "primary_knowledge_source": "infores:visionkb-heca",
               "publications": [], "evidence_count": 2, "status": "curated"}  # fmt: skip
        if not (r.query_params.get("subject") or r.query_params.get("object")):
            return env(None, status=400, error={"code": "missing_anchor", "message": "subject or object required"})
        return env(
            [row],
            {"limit": int(r.query_params.get("limit", 50)), "offset": int(r.query_params.get("offset", 0)), "total": 1},
        )

    async def evidence(r):
        return env({"edge": {"edge_id": r.path_params["edge_id"]}, "study_results": [
            {"dataset_id": "visionkb:ds-hrca-snrna", "level": "majorclass", "group_label": "Rod", "n_cells": 1000,
             "pct_expressing": 0.9, "pseudobulk_cp10k": 15.8}], "publications": []}, {"limit": 50, "offset": 0, "total": 1})  # fmt: skip

    async def gene_sets(r):
        return env([{"gene_id": "HGNC:10012", "symbol": "RHO", "score": 9.5, "evidence": [{"edge_id": EDGE}]}],
                   {"limit": 50, "offset": 0, "total": 1})  # fmt: skip

    async def atlas(r):
        return env([{"dataset_id": "visionkb:ds-hrca-snrna", "level": "majorclass", "group_label": "Rod", "gene_id": "HGNC:10012",
                     "gene_symbol": "RHO", "n_cells": 1000, "pct_expressing": 0.9, "pseudobulk_cp10k": 15.8,
                     "dataset_version": "heca-2026.05"}], {"limit": 50, "offset": 0, "total": 1})  # fmt: skip

    async def datasets(r):
        return env([{"id": "visionkb:ds-hrca-snrna", "title": "HECA Human Retina Cell Atlas, snRNA-seq", "access_level": "lab",
                     "tissue": ["UBERON:0000966"], "n_cells": 1000, "score": 1.0, "matched": []}],
                   {"limit": 50, "offset": 0, "total": 1})  # fmt: skip

    async def proposals(r):
        return env({"proposal_id": "should-never-be-reached"})

    routes = [
        Route("/v1/health", guard(health, auth=False)),
        Route("/v1/ready", guard(ready, auth=False)),
        Route("/v1/release", guard(release)),
        Route("/v1/entities/search", guard(search)),
        Route("/v1/entities/{curie}", guard(entity)),
        Route("/v1/relationships", guard(relationships)),
        Route("/v1/evidence/{edge_id}", guard(evidence)),
        Route("/v1/gene-sets", guard(gene_sets)),
        Route("/v1/atlas/expression", guard(atlas)),
        Route("/v1/datasets", guard(datasets)),
        Route("/v1/proposals", guard(proposals), methods=["GET", "POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.hits = hits
    return app
