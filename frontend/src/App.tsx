import { useEffect, useRef, useState } from "react";
import { search, stats, type Item, type SearchResponse, type Stats } from "./api";

const EXAMPLES: { type: string; queries: string[] }[] = [
  { type: "Single intent", queries: ["Mỹ Tâm đang hát trên sân khấu", "người mặc áo dài"] },
  { type: "Multi-intent", queries: ["Đen Vâu và Suboi", "Mỹ Tâm hoặc Hồ Ngọc Hà"] },
  { type: "Multi-hop", queries: ["vợ của Trấn Thành", "con gái của chồng Mỹ Linh", "vợ của người sáng lập Vingroup"] },
];

const TYPE_LABEL: Record<string, string> = {
  single: "Single intent",
  multi_intent: "Multi-intent",
  multi_hop: "Multi-hop",
};

const STATUS_TEXT: Record<string, string> = {
  no_results: "Không tìm thấy ảnh phù hợp.",
  no_verified_relation: "Chưa có quan hệ đã kiểm chứng trong kho dữ liệu cho truy vấn này.",
  no_images_for_target: "Đã tìm ra người cần tìm nhưng kho chưa có ảnh của người đó.",
  no_seed_entity: "Không nhận ra tên người hoặc tổ chức trong câu hỏi.",
  needs_clarification: "Tên này khớp với nhiều người, hãy chọn một.",
};
const REFINE_TEXT = "Tên này khớp với nhiều người, đang hiện ảnh của tất cả. Chỉ xem một người:";
const SPELLING_TEXT = "Không có ai đúng tên này trong kho. Có phải bạn muốn tìm:";

export default function App() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [clientMs, setClientMs] = useState<number | null>(null);
  const [corpus, setCorpus] = useState<Stats | null>(null);
  const [detail, setDetail] = useState<Item | null>(null);
  const inflight = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    stats().then(setCorpus);
  }, []);

  async function run(q: string, selected: string[] = []) {
    const text = q.trim();
    if (!text) return;
    inflight.current?.abort(); // an older response must never overwrite a newer one
    const controller = new AbortController();
    inflight.current = controller;
    setLoading(true);
    setError(null);
    const t0 = performance.now();
    try {
      const r = await search(text, selected, controller.signal);
      if (controller.signal.aborted) return;
      setResult(r);
      setClientMs(Math.round(performance.now() - t0));
    } catch (e) {
      if (!controller.signal.aborted) setError(String(e));
    } finally {
      if (inflight.current === controller) setLoading(false);
    }
  }

  function clear() {
    inflight.current?.abort();
    setQuery("");
    setResult(null);
    setError(null);
    setClientMs(null);
    setDetail(null);
    setLoading(false);
    input.current?.focus();
  }

  return (
    <div className="page">
      <header>
        <h1>Tìm ảnh</h1>
        {corpus && (
          <span className="muted">
            {corpus.serving_images.toLocaleString("vi-VN")} ảnh đã index
          </span>
        )}
      </header>

      <form
        className="searchbar"
        onSubmit={(e) => {
          e.preventDefault();
          run(query);
        }}
      >
        <div className="query">
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && clear()}
            placeholder="Ví dụ: vợ của Trấn Thành"
            aria-label="Truy vấn"
            autoFocus
          />
          {(query || result) && (
            <button type="button" className="clear" onClick={clear} aria-label="Xóa tìm kiếm" title="Xóa (Esc)">
              ×
            </button>
          )}
        </div>
        <button type="submit" disabled={loading}>
          {loading ? "Đang tìm…" : "Tìm"}
        </button>
      </form>

      <div className="examples">
        {EXAMPLES.map((g) => (
          <div key={g.type} className="example-row">
            <span className="muted">{g.type}</span>
            {g.queries.map((q) => (
              <button
                key={q}
                className="chip"
                onClick={() => {
                  setQuery(q);
                  run(q);
                }}
              >
                {q}
              </button>
            ))}
          </div>
        ))}
      </div>

      {error && <p className="error">Lỗi: {error}</p>}
      {result && (
        <Results
          result={result}
          clientMs={clientMs}
          onPick={(id) => run(query, [id])}
          onOpen={setDetail}
        />
      )}
      {detail && <Detail item={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function Results({
  result,
  clientMs,
  onPick,
  onOpen,
}: {
  result: SearchResponse;
  clientMs: number | null;
  onPick: (id: string) => void;
  onOpen: (item: Item) => void;
}) {
  const m = result.metrics;
  return (
    <section>
      <div className="summary">
        <span className="badge">{TYPE_LABEL[result.query_type] ?? result.query_type}</span>
        <span className="muted">
          máy chủ {Number(m.server_ms).toFixed(0)} ms
          {clientMs !== null && ` · trình duyệt ${clientMs} ms`}
          {m.cache_hit ? " · cache" : ""}
          {Number(m.llm_calls) > 0 ? ` · LLM ${m.input_tokens}+${m.output_tokens} token` : " · không gọi LLM"}
        </span>
      </div>

      <div className="interpretation">
        {result.interpretation.intents.map((it, i) => (
          <div key={i}>
            <strong>Ý định {i + 1}:</strong>{" "}
            {it.relations.length > 0 && <span>{it.relations.join(" → ")} của </span>}
            {it.seeds.map((s) => s.name).join(it.entity_operator === "all" ? " + " : ", ") || "(không có tên riêng)"}
            {it.visual_text && <span className="muted"> · mô tả: “{it.visual_text}”</span>}
            {it.fuzzy && <span className="muted"> · khớp gần đúng</span>}
          </div>
        ))}
      </div>

      {result.clarification_options.length > 0 && (
        <div className={result.status === "needs_clarification" ? "notice" : "refine"}>
          <p>
            {result.status !== "needs_clarification"
              ? REFINE_TEXT
              : result.clarification_options.every((o) => o.kind === "spelling")
                ? SPELLING_TEXT
                : STATUS_TEXT.needs_clarification}
          </p>
          {result.clarification_options.map((o) => (
            <div key={o.mention} className="example-row">
              <span className="muted">“{o.mention}”</span>
              {o.candidates.map((c) => (
                <button key={c.entity_id} className="chip" onClick={() => onPick(c.entity_id)}>
                  {c.name}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {result.groups.map((g) => (
        <div key={g.intent_id + g.label} className="group">
          <h2>{g.label}</h2>
          {g.explanation.length > 0 && <p className="path">{g.explanation.join("  ·  ")}</p>}
          {g.image_ids.length === 0 ? (
            <p className="muted">{STATUS_TEXT[g.status] ?? STATUS_TEXT.no_results}</p>
          ) : (
            <div className="grid">
              {g.image_ids.map((id) => {
                const item = result.items[id];
                return (
                  <button key={id} className="card" onClick={() => onOpen(item)}>
                    <img
                      src={item.thumb_url}
                      width={item.width}
                      height={item.height}
                      loading="lazy"
                      alt={item.entities.map((e) => e.name).join(", ")}
                    />
                    <span className="caption">{item.entities.map((e) => e.name).join(", ")}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

function Detail({ item, onClose }: { item: Item; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-body" onClick={(e) => e.stopPropagation()}>
        <img src={item.thumb_url} alt="" />
        <p>
          <strong>{item.entities.map((e) => e.name).join(", ")}</strong>
        </p>
        {item.description && <p className="muted">{item.description}</p>}
        <p className="muted">
          {item.width}×{item.height}
          {item.source_url && (
            <>
              {" · "}
              <a href={item.source_url} target="_blank" rel="noreferrer noopener">
                nguồn
              </a>
            </>
          )}
        </p>
        <button onClick={onClose}>Đóng</button>
      </div>
    </div>
  );
}
