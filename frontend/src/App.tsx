import { useState, type FormEvent } from "react";

// ---------- Types matching the API responses ----------
type ProfileRow = {
  id: number;
  email: string | null;
  status: string | null;
  acquisition_source: string | null;
  signup_date: string | null;
  last_open_date: string | null;
};
type EventRow = {
  occurred_at: string;
  source: string;
  event_type: string;
  page: string | null;
  utm_source: string | null;
  properties: Record<string, unknown> | null;
};
type ProfileDetail = ProfileRow & {
  identities: { kind: string; value: string }[];
  summary: { web_visits: number; app_events: number };
  events: EventRow[];
};
type Table = { title: string; columns: string[]; rows: unknown[][] };
type AssistantReply = { answer: string; tables: Table[]; trace: unknown[] };

// ---------- Helpers ----------
// The browser already holds the Basic-auth password from its login prompt and
// sends it with these same-site requests automatically.
async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(
    path,
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

function downloadCsv(filename: string, columns: string[], rows: unknown[][]) {
  // Quote every cell and double any quotes inside it (standard CSV escaping).
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [columns, ...rows].map((r) => r.map(cell).join(",")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  link.download = filename;
  link.click();
}

const PROFILE_COLUMNS: (keyof ProfileRow)[] = ["email", "status", "acquisition_source", "signup_date", "last_open_date"];
const toRows = (profiles: ProfileRow[]) => profiles.map((p) => PROFILE_COLUMNS.map((c) => p[c]));

function DataTable({ columns, rows, max = 200 }: { columns: string[]; rows: unknown[][]; max?: number }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, max).map((r, i) => (
            <tr key={i}>{r.map((v, j) => <td key={j}>{v === null || v === undefined ? "—" : String(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && <p className="muted">Showing {max} of {rows.length}. Export for the full list.</p>}
    </div>
  );
}

// ---------- Requirement 2: find anyone ----------
function Lookup() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ProfileRow[]>([]);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [error, setError] = useState("");

  async function search(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDetail(null);
    try {
      setResults(await api<ProfileRow[]>(`/api/profiles?q=${encodeURIComponent(query)}`));
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <section>
      <form onSubmit={search} className="row">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Email, visitor id, app user id or device id" />
        <button>Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      {!detail && results.length > 0 && (
        <ul className="results">
          {results.map((p) => (
            <li key={p.id}>
              <button className="link" onClick={async () => setDetail(await api<ProfileDetail>(`/api/profiles/${p.id}`))}>
                {p.email ?? `Profile #${p.id} (no email yet)`}
              </button>
              <span className="muted"> {p.status ?? "not a subscriber"}</span>
            </li>
          ))}
        </ul>
      )}
      {detail && (
        <div className="card">
          <button className="link" onClick={() => setDetail(null)}>← Back to results</button>
          <h2>{detail.email ?? `Profile #${detail.id}`}</h2>
          <div className="grid">
            <div><h3>Newsletter</h3>
              <p>Status: {detail.status ?? "—"}<br />Source: {detail.acquisition_source ?? "—"}<br />
                Signed up: {detail.signup_date ?? "—"}<br />Last open: {detail.last_open_date ?? "never"}</p>
            </div>
            <div><h3>Activity</h3>
              <p>Website visits: {detail.summary.web_visits}<br />App events: {detail.summary.app_events}</p>
            </div>
            <div><h3>Linked ids</h3>
              <p>{detail.identities.map((i) => <span key={i.value}>{i.kind}: {i.value}<br /></span>)}</p>
            </div>
          </div>
          <h3>Timeline (newest first, by when it happened)</h3>
          <DataTable
            columns={["when", "source", "event", "page / story", "utm"]}
            rows={detail.events.map((e) => [
              e.occurred_at.replace("T", " ").slice(0, 19),
              e.source,
              e.event_type,
              e.page ?? (e.properties?.story as string | undefined) ?? "",
              e.utm_source,
            ])}
          />
        </div>
      )}
    </section>
  );
}

// ---------- Requirement 3: build a segment ----------
type Filters = {
  source?: string; status?: string; signed_up_from?: string; signed_up_to?: string;
  not_opened_days?: number; min_events?: number; has_app?: boolean;
};

function Segments() {
  const [filters, setFilters] = useState<Filters>({ source: "instagram", not_opened_days: 30 });
  const [result, setResult] = useState<{ count: number; profiles: ProfileRow[] } | null>(null);
  const [error, setError] = useState("");

  const set = (key: keyof Filters, value: string, kind: "text" | "number" | "bool" = "text") =>
    setFilters((f) => {
      const next: Filters = { ...f };
      if (value === "") delete next[key];
      else (next as Record<string, unknown>)[key] = kind === "number" ? Number(value) : kind === "bool" ? value === "true" : value;
      return next;
    });

  async function run(f: Filters = filters) {
    setError("");
    try {
      setResult(await api("/api/segments", f));
    } catch (err) {
      setError(String(err));
    }
  }

  async function goingCold() {
    // The surprise feature: a saved preset for engaged readers who stopped opening.
    const presets = await api<Record<string, Filters>>("/api/segments/presets");
    setFilters(presets.going_cold);
    run(presets.going_cold);
  }

  return (
    <section>
      <div className="filters">
        <label>Source
          <select value={filters.source ?? ""} onChange={(e) => set("source", e.target.value)}>
            <option value="">Any</option>
            {["instagram", "facebook", "referral", "google", "direct", "podcast", "x"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>Status
          <select value={filters.status ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any</option><option>active</option><option>unsubscribed</option>
          </select>
        </label>
        <label>Signed up from<input type="date" value={filters.signed_up_from ?? ""} onChange={(e) => set("signed_up_from", e.target.value)} /></label>
        <label>Signed up to<input type="date" value={filters.signed_up_to ?? ""} onChange={(e) => set("signed_up_to", e.target.value)} /></label>
        <label>Not opened in (days)<input type="number" min={0} value={filters.not_opened_days ?? ""} onChange={(e) => set("not_opened_days", e.target.value, "number")} /></label>
        <label>Min. visits/events<input type="number" min={0} value={filters.min_events ?? ""} onChange={(e) => set("min_events", e.target.value, "number")} /></label>
        <label>App account
          <select value={filters.has_app === undefined ? "" : String(filters.has_app)} onChange={(e) => set("has_app", e.target.value, "bool")}>
            <option value="">Any</option><option value="true">Yes</option><option value="false">No</option>
          </select>
        </label>
      </div>
      <div className="row">
        <button onClick={() => run()}>Build segment</button>
        <button className="secondary" onClick={goingCold}>Going cold (preset)</button>
        {result && (
          <button className="secondary" onClick={() => downloadCsv("segment.csv", PROFILE_COLUMNS, toRows(result.profiles))}>
            Export CSV
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="count">{result.count} people</p>
          <DataTable columns={PROFILE_COLUMNS} rows={toRows(result.profiles)} />
        </>
      )}
    </section>
  );
}

// ---------- Requirement 5: talks back ----------
const EXAMPLES = [
  "How many Instagram signups went cold last month?",
  "Build me a list of our most engaged readers",
  "Which pages do new subscribers hit first?",
];

function Assistant() {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AssistantReply | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function askQuestion(q: string) {
    setQuestion(q);
    setLoading(true);
    setError("");
    setReply(null);
    try {
      setReply(await api<AssistantReply>("/api/assistant", { question: q }));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <form className="row" onSubmit={(e) => { e.preventDefault(); askQuestion(question); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your readers in plain English" />
        <button disabled={loading}>{loading ? "Thinking…" : "Ask"}</button>
      </form>
      <div className="chips">{EXAMPLES.map((q) => <button key={q} className="chip" onClick={() => askQuestion(q)}>{q}</button>)}</div>
      {error && <p className="error">{error}</p>}
      {reply && (
        <div className="card">
          <p className="answer">{reply.answer}</p>
          {reply.tables.map((t, i) => (
            <div key={i}>
              <div className="row">
                <h3>{t.title} ({t.rows.length})</h3>
                <button className="secondary" onClick={() => downloadCsv(`${t.title}.csv`, t.columns, t.rows)}>Export CSV</button>
              </div>
              <p className="muted">This list was built on the server and sent only to your browser. The AI never saw it.</p>
              <DataTable columns={t.columns} rows={t.rows} />
            </div>
          ))}
          <details>
            <summary>What the AI model actually saw</summary>
            <pre>{JSON.stringify(reply.trace, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}

const TABS = { Lookup, Segments, Assistant };

export default function App() {
  const [tab, setTab] = useState<keyof typeof TABS>("Lookup");
  const Current = TABS[tab];
  return (
    <main>
      <header>
        <h1>The Pour Over · Mini CDP</h1>
        <nav>
          {(Object.keys(TABS) as (keyof typeof TABS)[]).map((t) => (
            <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
      </header>
      <Current />
    </main>
  );
}
