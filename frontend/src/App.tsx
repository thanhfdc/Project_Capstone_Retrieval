import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { search, stats, type Item, type SearchResponse, type Stats } from "./api";
import { Icon } from "./icons";

const REPO_URL = "https://github.com/VSF-AR-ES-V-Lookup/DiemCongThanh_Project_Retrieval_Image";

const EXAMPLES: { type: string; kind: QueryKind; hint: string; queries: string[] }[] = [
  {
    type: "Single intent",
    kind: "single",
    hint: "Một người hoặc một cảnh",
    queries: ["Mỹ Tâm đang hát trên sân khấu", "người mặc áo dài", "Sơn Tùng M-TP"],
  },
  {
    type: "Multi-intent",
    kind: "multi_intent",
    hint: "Nhiều ý trong một câu",
    queries: ["Đen Vâu và Suboi", "Mỹ Tâm hoặc Hồ Ngọc Hà", "Hồ Ngọc Hà mặc áo dài và Đen Vâu trên sân khấu"],
  },
  {
    type: "Multi-hop",
    kind: "multi_hop",
    hint: "Suy ra người qua quan hệ",
    queries: ["ảnh con trai chủ tịch Phạm Nhật Vượng", "vợ của Trấn Thành", "con gái của chồng Mỹ Linh"],
  },
];

type QueryKind = SearchResponse["query_type"];

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

type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const t = localStorage.getItem("theme");
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(
    () => storedTheme() ?? (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("theme", next);
      } catch {
        /* private mode: the choice lasts for this visit only */
      }
      return next;
    });
  }, []);
  return [theme, toggle];
}

export default function App() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [clientMs, setClientMs] = useState<number | null>(null);
  const [corpus, setCorpus] = useState<Stats | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [theme, toggleTheme] = useTheme();
  const inflight = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    stats().then(setCorpus);
  }, []);

  // "/" focuses the search box from anywhere, like most search sites
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing && !detail) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detail]);

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

  function pick(q: string) {
    setQuery(q);
    run(q);
  }

  // every image of the result in display order, for the viewer's previous/next
  const order = useMemo(() => (result ? [...new Set(result.groups.flatMap((g) => g.image_ids))] : []), [result]);

  const idle = !result && !loading && !error;

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={clear} aria-label="Về trang đầu">
          <span className="logo">
            <Icon name="image" />
          </span>
          <span className="brand-text">
            <strong>
              Tìm ảnh người nổi tiếng <span className="nowrap">Việt Nam</span>
            </strong>
            <small>Capstone · Phần B</small>
          </span>
        </button>
        <div className="topbar-right">
          {corpus && (
            <span className="pill" title={`Encoder: ${corpus.encoder_online}`}>
              <span className="dot live" /> {corpus.serving_images.toLocaleString("vi-VN")} ảnh
            </span>
          )}
          <a className="icon-btn" href={REPO_URL} target="_blank" rel="noreferrer noopener" title="Mã nguồn">
            <Icon name="github" />
          </a>
          <button
            className="icon-btn"
            onClick={toggleTheme}
            title={theme === "dark" ? "Giao diện sáng" : "Giao diện tối"}
            aria-label="Đổi giao diện sáng/tối"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
        </div>
      </header>

      <main className={idle ? "page page-idle" : "page"}>
        {idle && (
          <div className="hero">
            <h1>
              Tìm ảnh <span className="grad">người nổi tiếng Việt Nam</span>
            </h1>
            <p>
              Gõ tên ca sĩ, diễn viên, vận động viên, chính trị gia…, mô tả cảnh hoặc quan hệ như "vợ của…", "con trai của…". Hệ thống hiểu câu hỏi rồi tìm
              trong {corpus ? corpus.serving_images.toLocaleString("vi-VN") : "hơn 80.000"} ảnh, dưới 3 giây.
            </p>
          </div>
        )}

        <form
          className="searchbar"
          onSubmit={(e) => {
            e.preventDefault();
            run(query);
          }}
        >
          <span className="search-icon">
            <Icon name="search" />
          </span>
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && clear()}
            placeholder="Ví dụ: ảnh con trai chủ tịch Phạm Nhật Vượng"
            aria-label="Truy vấn"
            autoFocus
          />
          {query ? (
            <button type="button" className="clear" onClick={clear} aria-label="Xóa tìm kiếm" title="Xóa (Esc)">
              <Icon name="x" />
            </button>
          ) : (
            <kbd className="kbd-hint" title="Nhấn / để gõ">
              /
            </kbd>
          )}
          <button type="submit" className="go" disabled={loading || !query.trim()}>
            {loading ? <span className="spinner" aria-hidden /> : <Icon name="arrow" />}
            <span>{loading ? "Đang tìm" : "Tìm"}</span>
          </button>
        </form>

        {idle ? (
          <div className="examples">
            {EXAMPLES.map((g) => (
              <div key={g.type} className={`example-card kind-${g.kind}`}>
                <div className="example-head">
                  <span className={`badge kind-${g.kind}`}>{g.type}</span>
                  <span className="muted">{g.hint}</span>
                </div>
                <div className="example-list">
                  {g.queries.map((q) => (
                    <button key={q} className="example" onClick={() => pick(q)}>
                      <span>{q}</span>
                      <Icon name="arrow" />
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="chips-row" aria-label="Câu ví dụ">
            {EXAMPLES.flatMap((g) =>
              g.queries.slice(0, 2).map((q) => (
                <button key={q} className={`chip kind-${g.kind}`} onClick={() => pick(q)}>
                  {q}
                </button>
              )),
            )}
          </div>
        )}

        {error && (
          <div className="alert alert-error">
            <Icon name="alert" />
            <span>Không gọi được máy chủ ({error}). Thử lại sau giây lát.</span>
          </div>
        )}

        {loading && !result && <Skeleton />}

        {result && (
          <div className={loading ? "results is-loading" : "results"}>
            <Results result={result} clientMs={clientMs} onPick={(id) => run(query, [id])} onOpen={setDetail} />
          </div>
        )}
      </main>

      <footer className="footer">
        <span>FastAPI · PostgreSQL pgvector · SigLIP 2 · React</span>
        <span className="sep">·</span>
        <a href={REPO_URL} target="_blank" rel="noreferrer noopener">
          Mã nguồn và tài liệu
        </a>
      </footer>

      {detail && result && (
        <Viewer result={result} order={order} id={detail} onMove={setDetail} onClose={() => setDetail(null)} />
      )}
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
  onOpen: (id: string) => void;
}) {
  const m = result.metrics;
  const total = new Set(result.groups.flatMap((g) => g.image_ids)).size;
  const llm = Number(m.llm_calls) > 0;
  const asking = result.status === "needs_clarification";
  const seedNames = shortNames(result.interpretation.intents.flatMap((it) => it.seeds.map((s) => s.name)));
  return (
    <section>
      <div className="summary">
        <span className={`badge kind-${result.query_type}`}>{TYPE_LABEL[result.query_type] ?? result.query_type}</span>
        <span className="summary-count">{total > 0 ? `${total} ảnh` : asking ? "Cần bạn chọn người" : "Không có ảnh"}</span>
        <span className="metrics">
          {!m.cache_hit && (
            <span className="metric" title="Thời gian xử lý trên máy chủ">
              <Icon name="bolt" /> {Number(m.server_ms).toFixed(0)} ms
            </span>
          )}
          {clientMs !== null && (
            <span className="metric" title="Thời gian từ lúc bấm tìm tới khi nhận kết quả">
              <Icon name="clock" /> {clientMs} ms
            </span>
          )}
          {m.cache_hit ? <span className="metric" title="Câu này vừa được tìm, kết quả lấy lại từ bộ nhớ đệm">cache</span> : null}
          <span className="metric" title="Câu hỏi được phân tích bằng bộ luật, không tốn token">
            {llm ? `LLM ${m.input_tokens}+${m.output_tokens} token` : "không gọi LLM"}
          </span>
        </span>
      </div>

      {!asking && <Interpretation result={result} />}

      {result.clarification_options.length > 0 && <Clarify result={result} onPick={onPick} />}

      {result.groups.map((g) => (
        <div key={g.intent_id + g.label} className="group">
          <div className="group-head">
            <h2>{prettyLabel(g.label, seedNames)}</h2>
            {g.image_ids.length > 0 && <span className="count">{g.image_ids.length}</span>}
          </div>
          {g.explanation.length > 0 && (
            <div className="paths">
              {g.explanation.map((e) => (
                <Path key={e} text={e} />
              ))}
            </div>
          )}
          {g.image_ids.length === 0 ? (
            <div className="empty">
              <Icon name="image" />
              <span>{STATUS_TEXT[g.status] ?? STATUS_TEXT.no_results}</span>
            </div>
          ) : (
            <div className="grid">
              {g.image_ids.map((id, i) => {
                const item = result.items[id];
                const names = shortNames(item.entities.map((e) => e.name)).join(", ");
                return (
                  <button
                    key={id}
                    className="card"
                    style={{ animationDelay: `${Math.min(i, 12) * 25}ms` }}
                    onClick={() => onOpen(id)}
                    title={item.description || names}
                  >
                    <img src={item.thumb_url} width={item.width} height={item.height} loading="lazy" alt={names} />
                    <span className="caption">{names || "Ảnh"}</span>
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

function Interpretation({ result }: { result: SearchResponse }) {
  const { intents, location, location_text, combine } = result.interpretation;
  return (
    <div className="understood">
      <div className="understood-title">
        <Icon name="spark" /> Hệ thống hiểu câu hỏi
        {intents.length > 1 && (
          <span className="muted">
            {" "}
            · {intents.length} ý, {combine === "union" ? "lấy ảnh của một trong các ý" : "mỗi ý một nhóm ảnh"}
          </span>
        )}
      </div>
      {intents.map((it, i) => {
        const names = shortNames(it.seeds.map((s) => s.name));
        return (
          <div key={i} className="intent">
            {intents.length > 1 && <span className="step">{i + 1}</span>}
            <div className="intent-body">
              {names.length > 0 ? (
                names.slice(0, 4).map((n, j) => (
                  <span key={n} className="tok tok-person">
                    {j > 0 && <em>{it.entity_operator === "all" ? "+" : "/"}</em>}
                    <Icon name="user" /> {n}
                  </span>
                ))
              ) : (
                <span className="tok tok-none">không có tên riêng</span>
              )}
              {names.length > 4 && <span className="muted">+{names.length - 4}</span>}
              {it.relations.map((r) => (
                <span key={r} className="tok tok-rel">
                  <Icon name="arrow" /> {r}
                </span>
              ))}
              {it.visual_text && <span className="tok tok-text">“{it.visual_text}”</span>}
              {it.fuzzy && <span className="tok tok-flag">khớp gần đúng</span>}
            </div>
          </div>
        );
      })}
      {(location || location_text) && (
        <div className="intent">
          <div className="intent-body">
            <span className="tok tok-place">
              <Icon name="pin" /> {location?.name ?? location_text}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

const fold = (s: string) =>
  s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/gi, "d").toLowerCase();

// one chip per person: the crawled duplicates a name matched ("Mỹ Linh (ca sĩ)", "Chân dung studio Phạm Nhật
// Vượng Forbes") read as the shortest name they contain
function shortNames(names: string[]): string[] {
  const kept: string[] = [];
  for (const n of [...new Set(names)].sort((a, b) => a.length - b.length)) {
    if (!kept.some((k) => fold(n).includes(fold(k.split(/\s*[([]|\s+[-–|,]\s+/)[0])))) kept.push(n);
  }
  return kept.map((n) => n.split(/\s*[([]/)[0]);
}

const norm = (s: string) => fold(s).replace(/[^a-z0-9]+/g, " ").trim();

// group labels come back folded to lower case ("son tung m tp" style); put each matched person's own spelling back
function prettyLabel(label: string, names: string[]): string {
  let words = label.split(/\s+/).filter(Boolean);
  for (const name of [...names].sort((a, b) => b.length - a.length)) {
    const want = norm(name).split(" ");
    for (let i = 0; i + want.length <= words.length; i++) {
      if (want.every((w, j) => norm(words[i + j]) === w)) {
        words = [...words.slice(0, i), name, ...words.slice(i + want.length)];
        break;
      }
    }
  }
  const out = words.join(" ");
  return out.charAt(0).toUpperCase() + out.slice(1);
}

function Clarify({ result, onPick }: { result: SearchResponse; onPick: (id: string) => void }) {
  const blocking = result.status === "needs_clarification";
  const text = !blocking
    ? REFINE_TEXT
    : result.clarification_options.every((o) => o.kind === "spelling")
      ? SPELLING_TEXT
      : STATUS_TEXT.needs_clarification;
  return (
    <div className={blocking ? "alert alert-ask" : "refine"}>
      {blocking && <Icon name="help" />}
      <div className="clarify-body">
        <p>{text}</p>
        {result.clarification_options.map((o) => (
          <div key={o.mention} className="clarify-row">
            <span className="muted">“{o.mention}”</span>
            {o.candidates.map((c) => (
              <button key={c.entity_id} className="candidate" onClick={() => onPick(c.entity_id)}>
                <Icon name="user" /> {c.name}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// "Mỹ Linh → chồng → Anh Quân (nhạc sĩ)" drawn as person, relation, person
function Path({ text }: { text: string }) {
  const parts = text.split(" → ");
  if (parts.length !== 3) return <span className="path-text">{text}</span>;
  return (
    <span className="path">
      <span className="tok tok-person">{parts[0]}</span>
      <span className="path-rel">
        <Icon name="arrow" /> {parts[1]} <Icon name="arrow" />
      </span>
      <span className="tok tok-person tok-target">{parts[2]}</span>
    </span>
  );
}

function Skeleton() {
  return (
    <div className="results" aria-busy="true" aria-label="Đang tìm">
      <div className="skeleton-line" />
      <div className="grid">
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} className="card skeleton" />
        ))}
      </div>
    </div>
  );
}

function Viewer({
  result,
  order,
  id,
  onMove,
  onClose,
}: {
  result: SearchResponse;
  order: string[];
  id: string;
  onMove: (id: string) => void;
  onClose: () => void;
}) {
  const item: Item = result.items[id];
  const at = order.indexOf(id);
  const prev = at > 0 ? order[at - 1] : null;
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && prev) onMove(prev);
      else if (e.key === "ArrowRight" && next) onMove(next);
    };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose, onMove, prev, next]);

  return (
    <div className="viewer" onClick={onClose} role="dialog" aria-modal="true" aria-label="Xem ảnh">
      <div className="viewer-body" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-image">
          <img key={id} src={item.thumb_url} alt={item.entities.map((e) => e.name).join(", ")} />
          {prev && (
            <button className="nav nav-prev" onClick={() => onMove(prev)} aria-label="Ảnh trước (←)">
              <Icon name="chevron-left" />
            </button>
          )}
          {next && (
            <button className="nav nav-next" onClick={() => onMove(next)} aria-label="Ảnh sau (→)">
              <Icon name="chevron-right" />
            </button>
          )}
        </div>
        <aside className="viewer-info">
          <button className="icon-btn viewer-close" onClick={onClose} aria-label="Đóng (Esc)" title="Đóng (Esc)">
            <Icon name="x" />
          </button>
          <div className="viewer-people">
            {shortNames(item.entities.map((e) => e.name)).map((n) => (
              <span key={n} className="tok tok-person">
                <Icon name="user" /> {n}
              </span>
            ))}
          </div>
          {item.description && <p className="viewer-desc">{item.description}</p>}
          <dl className="facts">
            <dt>Kích thước</dt>
            <dd>
              {item.width} × {item.height}
            </dd>
            {at >= 0 && (
              <>
                <dt>Thứ tự</dt>
                <dd>
                  {at + 1} / {order.length}
                </dd>
              </>
            )}
          </dl>
          <div className="viewer-links">
            {item.source_url && (
              <a className="btn" href={item.source_url} target="_blank" rel="noreferrer noopener">
                <Icon name="link" /> Trang nguồn
              </a>
            )}
            {item.image_url && (
              <a className="btn btn-ghost" href={item.image_url} target="_blank" rel="noreferrer noopener">
                <Icon name="image" /> Ảnh gốc
              </a>
            )}
          </div>
          <p className="muted viewer-keys">← → để chuyển ảnh · Esc để đóng</p>
        </aside>
      </div>
    </div>
  );
}
