"""Search orchestration: parse -> resolve relations -> retrieve -> fuse -> hydrate."""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from ..config import Settings
from ..textnorm import fold
from . import relations as rel
from . import retriever as R
from .entity_linker import EntityLinker, EntityRef, person_key
from .query_parser import Intent, QueryPlan, RuleParser


@dataclass
class Timer:
    marks: dict[str, float] = field(default_factory=dict)
    _t: float = field(default_factory=time.perf_counter)

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.marks[name] = round(self.marks.get(name, 0.0) + (now - self._t) * 1000, 2)
        self._t = now


class SearchService:
    def __init__(self, settings: Settings, pool, encoder, linker: EntityLinker, llm=None):
        self.s = settings
        self.pool = pool
        self.encoder = encoder
        self.linker = linker
        self.llm = llm
        self.parser = RuleParser(lambda: linker.index, linker.fuzzy)
        self._encode_lock = threading.Semaphore(1)
        self._cache: OrderedDict = OrderedDict()
        self._cache_lock = threading.Lock()
        self.snapshot = "unknown"

    # ---- public -------------------------------------------------------------------------
    def search(self, query: str, top_k: int, selected_entity_ids: list[str] | None = None,
               use_cache: bool = True) -> dict:
        started = time.perf_counter()
        # accents and capitals change who a name is ("Xuân Bắc" is not "Xuân Ba"), so the key keeps them
        key = (" ".join(query.split()), top_k, tuple(sorted(selected_entity_ids or [])), self.snapshot)
        if use_cache and self.s.result_cache_enabled:
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit is not None:
                    self._cache.move_to_end(key)
            if hit is not None:
                out = {**hit, "request_id": f"req_{uuid.uuid4().hex[:12]}"}
                out["metrics"] = {**hit["metrics"], "cache_hit": True,
                                  "server_ms": round((time.perf_counter() - started) * 1000, 2)}
                return out

        timer = Timer()
        usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        plan = self.parser.parse(query)
        timer.lap("parse_ms")
        if self.llm and self._needs_llm(plan):
            plan = self._llm_replan(query, plan, usage)
            timer.lap("llm_ms")

        selected = set(selected_entity_ids or [])
        blocking, refine = self._resolve_ambiguity(plan, selected)
        if blocking:
            return self._finish(key, started, timer, usage, plan, "needs_clarification", [], {}, [],
                                blocking, cache=False)

        with self.pool.connection() as conn:
            groups, paths, warnings = self._run(conn, plan, top_k, timer)
            ids = list(dict.fromkeys(i for g in groups for i in g["image_ids"]))
            items = R.hydrate(conn, ids)
            timer.lap("hydrate_ms")
        for g in groups:
            g["image_ids"] = [i for i in g["image_ids"] if i in items]
        status = self._overall_status(groups)
        plan.warnings += warnings
        return self._finish(key, started, timer, usage, plan, status, groups, items, paths, refine)

    def stats(self) -> dict:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot'").fetchone()
            enc = conn.execute("SELECT value FROM meta WHERE key = 'encoder'").fetchone()
            live = conn.execute("SELECT count(*) AS n FROM images WHERE is_serving").fetchone()
        import json
        snap = json.loads(row["value"]) if row else {}
        return {"serving_images": live["n"], "encoder_offline": enc["value"] if enc else None,
                "encoder_online": getattr(self.encoder, "name", "?"), "snapshot": snap,
                "api_workers": int(os.environ.get("WEB_CONCURRENCY", "1")),
                "encoder_threads": self.s.encoder_threads, "db_pool_max": self.s.db_pool_max}

    # ---- planning helpers ---------------------------------------------------------------
    def _needs_llm(self, plan: QueryPlan) -> bool:
        """Relation words were used but no seed entity was found: the rules could not plan it."""
        for it in plan.intents:
            if it.relation_steps and not it.seeds:
                return True
        words = set(fold(plan.query).split())
        has_rel_word = bool(words & {"con", "vo", "chong", "bo", "me", "cha", "sang", "thanh"})
        return has_rel_word and not any(it.seeds or it.ambiguous for it in plan.intents)

    def _llm_replan(self, query: str, plan: QueryPlan, usage: dict) -> QueryPlan:
        from .llm import label_to_step

        llm_plan, used = self.llm.plan(query)
        for k in ("llm_calls", "input_tokens", "output_tokens"):
            usage[k] += used.get(k, 0)
        if llm_plan is None or llm_plan.needs_clarification:
            plan.warnings.append("llm_fallback_unavailable" if llm_plan is None else "llm_needs_clarification")
            return plan
        intents = []
        for li in llm_plan.intents:
            seeds, ambiguous = [], []
            for mention in li.entity_mentions:
                spans = self.linker.index.find_spans(fold(mention).split()) or self.linker.fuzzy(fold(mention).split())
                for s in spans:
                    (ambiguous if s.ambiguous else seeds).append(s if s.ambiguous else s.candidates[0])
            steps = [s for s in (label_to_step(lbl) for lbl in reversed(li.relation_chain)) if s]
            intents.append(Intent(label=" ".join(li.entity_mentions + [li.visual_text]).strip() or query,
                                  seeds=seeds, relation_steps=steps, visual_text=li.visual_text,
                                  lexical_text=fold(li.visual_text), ambiguous=ambiguous,
                                  entity_operator="all" if len(seeds) > 1 and not steps else "any"))
        if intents and any(i.seeds or i.ambiguous for i in intents):
            plan.intents = intents[:3]
            plan.parser = "llm"
            plan.query_type = "multi_hop" if any(i.relation_steps for i in intents) else \
                ("multi_intent" if len(intents) > 1 else "single")
        return plan

    def _resolve_ambiguity(self, plan: QueryPlan, selected: set[str]) -> tuple[list[dict], list[dict]]:
        """Return (blocking, refine) options. A name shared by several entities is searched as all
        of them right away, with the candidates offered as optional refinements. Only "A chụp cùng B"
        blocks, because "same photo as one of several people" has no sensible default."""
        blocking, refine = [], []
        for it in plan.intents:
            together = len({person_key(s.name) for s in it.seeds}) + len(it.ambiguous) > 1
            unresolved = []
            for span in it.ambiguous:
                chosen = [c for c in span.candidates if c.entity_id in selected]
                option = {"mention": span.text, "kind": "spelling" if span.confirm else "same_name", "candidates": [
                    {"entity_id": c.entity_id, "name": c.name, "entity_type": c.entity_type}
                    for c in span.candidates]}
                one_person = len({person_key(c.name) for c in span.candidates}) == 1
                if chosen:
                    it.seeds.extend(chosen)
                elif span.confirm:  # "Vân Dung" is not Văn Dung: show nobody's photos until the user says so
                    unresolved.append(span)
                    blocking.append(option)
                elif one_person:  # duplicates of one person ("Mỹ Tâm", "Mỹ Tâm (queen Vpop)"): search them all
                    it.seeds.extend(span.candidates)
                elif together:
                    unresolved.append(span)
                    blocking.append(option)
                else:
                    it.seeds.extend(span.candidates)
                    refine.append(option)
            it.ambiguous = unresolved
            if together and not unresolved and len({person_key(s.name) for s in it.seeds}) > 1:
                it.entity_operator = "all"
        return blocking, refine

    # ---- execution ----------------------------------------------------------------------
    def _encode(self, texts: list[str]):
        with self._encode_lock:
            return self.encoder.encode_texts(texts)

    def _run(self, conn, plan: QueryPlan, top_k: int, timer: Timer):
        names: dict[str, str] = {}
        for it in plan.intents:
            for s in it.seeds:
                names[s.entity_id] = s.name
        warnings: list[str] = []
        location_scope = None
        if plan.location:
            location_scope = rel.place_scope(conn, plan.location.entity_id)

        # Resolve relations and place seeds first, so every visual text is encoded in one batch.
        jobs = []  # (label, entity ids or None, operator, visual, lexical, scope, status, paths)
        all_paths = []
        for n, it in enumerate(plan.intents):
            seed_ids = [s.entity_id for s in it.seeds]
            persons = [s for s in it.seeds if s.entity_type != "place"]
            places = [s for s in it.seeds if s.entity_type == "place"]
            scope = location_scope
            if it.unknown_name:  # "Jack Ma" must not return "Jack", nor strangers who look alike
                jobs.append((n, it.label, [], "any", "", "", None, "no_seed_entity", []))
                continue
            if it.unknown_relation:
                jobs.append((n, it.label, [], "any", "", "", None, "no_verified_relation", []))
                continue
            if it.relation_steps:
                if not seed_ids:
                    jobs.append((n, it.label, [], "any", "", "", None, "no_seed_entity", []))
                    continue
                targets, hops, status = rel.follow(conn, seed_ids, it.relation_steps[:2], names)
                timer.lap("relation_ms")
                all_paths += [hop.__dict__ for hop in hops]
                if status == "frontier_truncated":
                    warnings.append("relation frontier truncated to 50 entities")
                if not targets:
                    jobs.append((n, it.label, [], "any", "", "", None, status, hops))
                    continue
                # one group per target person ("con trai của X: A", "...: B")
                for t in targets:
                    label = f"{it.relation_steps[-1].label} của {self._chain_label(it, names)}: {names.get(t, t)}"
                    jobs.append((n, label, [t], "any", it.visual_text, it.lexical_text, scope, "ok",
                                 self._chain_to(hops, t)))
                continue
            if places and not persons:
                place_ids = [i for p in places for i in rel.place_scope(conn, p.entity_id)]
                visual = it.visual_text or it.label
                place_words = " ".join(fold(p.name) for p in places)
                jobs.append((n, it.label, None, "any", f"{visual} {' '.join(p.name for p in places)}".strip(),
                             f"{it.lexical_text} {place_words}".strip(), place_ids, "ok", []))
                continue
            ids = [s.entity_id for s in persons] if persons else None
            jobs.append((n, it.label, ids, it.entity_operator, it.visual_text, it.lexical_text, scope, "ok", []))

        texts = sorted({j[4] for j in jobs if j[4] and j[7] == "ok"})
        vectors = dict(zip(texts, self._encode(texts))) if texts else {}
        timer.lap("encode_ms")

        groups = []
        k = top_k if plan.combine == "union" or len(plan.intents) == 1 else max(top_k // len(plan.intents), 4)
        for n, label, ids, operator, visual, lexical, scope, status, hops in jobs:
            group = {"intent_id": f"i{n + 1}", "label": label, "status": status, "image_ids": [],
                     "explanation": [f"{h.from_name} → {h.label} → {h.to_name}" for h in hops]}
            if status != "ok":
                groups.append(group)
                continue
            group["image_ids"], group["retrieval"] = self._retrieve(conn, ids, operator, visual, lexical,
                                                                    scope, vectors.get(visual), k,
                                                                    fold(plan.location_text))
            if not group["image_ids"]:
                group["status"] = "no_images_for_target" if hops else "no_results"
            groups.append(group)
        timer.lap("retrieval_ms")

        if plan.combine == "union" and len(groups) > 1:
            fused = R.fuse_rrf([g["image_ids"] for g in groups], k_rrf=self.s.rrf_k)
            groups = [{"intent_id": "union", "label": " hoặc ".join(g["label"] for g in groups),
                       "status": "ok" if fused else "no_results",
                       "image_ids": [i for i, _ in fused[:top_k]], "explanation": []}]
        return groups, all_paths, warnings

    @staticmethod
    def _chain_to(hops, target: str) -> list:
        """The hops that lead to one target, in reading order (seed first)."""
        chain, current = [], target
        for hop in reversed(hops):
            if hop.to_id == current:
                chain.append(hop)
                current = hop.from_id
        return list(reversed(chain))

    def _chain_label(self, it: Intent, names: dict) -> str:
        seed = ", ".join(s.name for s in it.seeds)
        for step in it.relation_steps[:-1]:
            seed = f"{step.label} {seed}"
        return seed

    def _retrieve(self, conn, ids, operator, visual, lexical, scope, qvec, k, extra=""):
        """Return (ranked image ids, which branches ran)."""
        cand = self.s.candidate_k
        if ids is not None:
            if operator == "all" and len(ids) > 1:  # same photo
                # same-photo: only images linked to all entities; then rank by visual text if any
                by_id, keys = self.linker.index.by_id, {}
                groups = [keys.setdefault(person_key(by_id[i].name) if i in by_id else i, len(keys)) for i in ids]
                base = R.images_by_entities(conn, ids, "all", cand, groups)
                if not base or qvec is None:
                    return base[:k], ["entity_sql"]
                ranked = R.vector_search(conn, qvec, cand, ids)
                order = [i for i, _ in ranked if i in set(base)]
                return (order + [i for i in base if i not in order])[:k], ["entity_sql", "vector"]
            if not visual:
                return R.images_by_entities(conn, ids, "any", k), ["entity_sql"]
            vec = R.vector_search(conn, qvec, cand, ids) if qvec is not None else []
            lex = R.lexical_search(conn, lexical, cand, ids)
            fused = R.fuse_rrf([[i for i, _ in vec], [i for i, _ in lex]], k_rrf=self.s.rrf_k)
            return [i for i, _ in fused[:k]], ["vector", "lexical"]

        # no entity: images of a place if one was named, else the whole corpus
        if scope:
            vec = R.vector_search(conn, qvec, cand, scope) if qvec is not None else []
            lex = R.lexical_search(conn, lexical, cand, scope)
        if not scope or (not vec and not lex):
            # nothing narrows the search, so only confident matches count
            vec = R.vector_search(conn, qvec, cand, None) if qvec is not None else []
            vec = [(i, score) for i, score in vec if score >= self.s.min_visual_score]
            lex = R.lexical_search(conn, lexical, cand, None, require_all=True)
            fused = [i for i, _ in R.fuse_rrf([[i for i, _ in vec], [i for i, _ in lex]], k_rrf=self.s.rrf_k)]
            if len(fused) >= k:
                return fused[:k], ["vector", "lexical"]
            # too few confident matches: add captions that share most of the description, ordered by how
            # much of it they say and by how close the photo looks
            core = lexical[:-len(extra)].strip() if extra and lexical.endswith(extra) else lexical
            partial = R.lexical_partial(conn, core, cand, extra, self.linker.index.name_pairs)
            ranked = R.rank_by_vector(conn, qvec, partial) if qvec is not None else partial
            more = [i for i, _ in R.fuse_rrf([partial, ranked], k_rrf=self.s.rrf_k) if i not in set(fused)]
            return (fused + more)[:k], ["vector", "lexical", "lexical_partial"]
        fused = R.fuse_rrf([[i for i, _ in vec], [i for i, _ in lex]], k_rrf=self.s.rrf_k)
        return [i for i, _ in fused[:k]], ["vector", "lexical"]

    @staticmethod
    def _overall_status(groups: list[dict]) -> str:
        if not groups:
            return "no_results"
        if any(g["status"] == "ok" and g["image_ids"] for g in groups):
            return "ok" if all(g["image_ids"] for g in groups) else "partial"
        statuses = [g["status"] for g in groups]
        for s in ("no_verified_relation", "no_seed_entity", "no_images_for_target"):
            if s in statuses:
                return s
        return "no_results"

    def _finish(self, key, started, timer, usage, plan, status, groups, items, paths, clarifications,
                cache=True) -> dict:
        def ref(e: EntityRef):
            return {"entity_id": e.entity_id, "name": e.name, "entity_type": e.entity_type}

        out = {
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "status": status,
            "query_type": plan.query_type,
            "interpretation": {
                "parser": plan.parser,
                "combine": plan.combine,
                "location": ref(plan.location) if plan.location else None,
                "location_text": plan.location_text,
                "intents": [{"label": it.label, "seeds": [ref(s) for s in it.seeds],
                             "entity_operator": it.entity_operator,
                             "relations": [s.label for s in reversed(it.relation_steps)],
                             "visual_text": it.visual_text, "fuzzy": it.fuzzy} for it in plan.intents],
            },
            "groups": groups,
            "items": items,
            "relation_paths": paths,
            "clarification_options": clarifications,
            "warnings": plan.warnings,
            "corpus_snapshot": self.snapshot,
            "metrics": {**timer.marks, **usage, "cache_hit": False,
                        "server_ms": round((time.perf_counter() - started) * 1000, 2)},
        }
        if cache and self.s.result_cache_enabled and status in ("ok", "partial"):
            with self._cache_lock:
                self._cache[key] = out
                self._cache.move_to_end(key)
                while len(self._cache) > self.s.result_cache_size:
                    self._cache.popitem(last=False)
        return out
