import { useEffect, useState } from "react";
import { getJSON, postJSON, uploadSource, useApi, fmt } from "../api.js";
import { Loading } from "../components.jsx";

function todayLocal() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export default function Sources() {
  const [version, setVersion] = useState(0);
  const [sourceKey, setSourceKey] = useState("");
  const [file, setFile] = useState(null);
  const [system, setSystem] = useState("");
  const [snapshotDate, setSnapshotDate] = useState(todayLocal);
  const [uploaded, setUploaded] = useState(null);
  const [job, setJob] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sources = useApi("data-sources", null, [version]);
  const jobs = useApi("data-sources/processing-jobs", { limit: 5 }, [version]);

  useEffect(() => {
    if (!job?.id || !["queued", "running"].includes(job.status)) return undefined;
    const timer = setInterval(() => {
      getJSON(`data-sources/processing-jobs/${job.id}`)
        .then(setJob)
        .catch((e) => setError(e.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);

  async function submit(event) {
    event.preventDefault();
    if (!sourceKey || !file) return;
    setBusy(true); setMessage(""); setError(""); setJob(null);
    try {
      const result = await uploadSource(sourceKey, file, { system, snapshotDate });
      setUploaded({ sourceKey, result, fileName: file.name });
      setMessage(result.duplicate
        ? "This source file is already stored. Run the import to convert it into the project’s Parquet datasets."
        : `Stored ${file.name}. Run the import to convert it into Parquet and update the dashboard.`);
      setFile(null);
      event.target.reset();
      setVersion((v) => v + 1);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function importData() {
    setBusy(true); setError("");
    try {
      const created = await postJSON("data-sources/processing-jobs", { job_type: "refresh_data" });
      setJob(created);
      setMessage(`Import queued as job ${created.id}.`);
      setVersion((v) => v + 1);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return <>
    <h1>Sources & uploads</h1>
    <p className="lede">Upload source files, then import them to rebuild the dashboard from the saved data.</p>
    <section>
      <h2>Add a source file</h2>
      <form className="filters" onSubmit={submit}>
        <select aria-label="Input type" value={sourceKey} onChange={(e) => setSourceKey(e.target.value)} required>
          <option value="">Choose the input type</option>
          {(sources.data || []).map((s) => <option key={s.source} value={s.source}>{s.label}</option>)}
        </select>
        {sourceKey === "hospital_mrf" && <>
          <label>Hospital system key
            <input value={system} onChange={(e) => setSystem(e.target.value)} placeholder="e.g. cleveland_clinic" required />
          </label>
          <label>Snapshot date
            <input type="date" value={snapshotDate} onChange={(e) => setSnapshotDate(e.target.value)} required />
          </label>
        </>}
        <input type="file" aria-label="Source file" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
        <button className="button" disabled={busy || !file || !sourceKey || (sourceKey === "hospital_mrf" && !system.trim())}>
          {busy ? "Uploading…" : "Upload file"}
        </button>
      </form>
      <p className="muted">The import step converts supported uploads into the project’s Parquet datasets. After import, dashboard and comparison reads use Parquet; originals remain stored for source lineage. Hospital MRF uploads need a system key and snapshot date.</p>
      {message && <p role="status" className="success-message">{message}</p>}
      {error && <p role="alert" className="note error">{error}</p>}
      {uploaded && <div className="import-action">
        <p>Ready to convert <b>{uploaded.fileName}</b> into the project’s Parquet datasets.</p>
        <button className="button" type="button" onClick={importData} disabled={busy || ["queued", "running"].includes(job?.status)}>
          {busy ? "Queueing…" : "Import data and rebuild dashboard"}
        </button>
      </div>}
    </section>
    {job && <section aria-live="polite">
      <h2>Import job {job.id}</h2>
      <p><b>{job.status}</b>{job.progress != null ? ` · ${job.progress}%` : ""}</p>
      {job.status === "queued" && <p className="note">The job is queued. Start the data worker from the backend folder with <code>python manage.py process_jobs</code>.</p>}
      {job.status === "failed" && <pre className="note error import-log">{job.error || job.summary?.output_tail || "The import failed without a diagnostic message."}</pre>}
      {job.status === "succeeded" && <p className="success-message">Import complete. {fmt.n(job.summary?.parquet_converted_sources || 0)} uploaded source file(s) were converted. The dashboard and comparisons now read the saved Parquet datasets; original uploads are retained for audit history.</p>}
      {job.summary?.output_tail && job.status === "running" && <details><summary>Import log</summary><pre className="import-log">{job.summary.output_tail}</pre></details>}
    </section>}
    <Loading state={jobs}>{(rows) => rows.length > 0 && <section>
      <h2>Recent imports</h2>
      <ul>{rows.map((row) => <li key={row.id}>Job {row.id}: {row.job_type} · {row.status} · {fmt.n(row.progress)}%</li>)}</ul>
    </section>}</Loading>
    <Loading state={sources}>{(rows) => <section>
      <h2>Required and supplemental inputs</h2>
      <div className="source-grid">{rows.map((s) => <article className="source-card" key={s.source}>
        <div className="source-title"><h3>{s.label}</h3><span className={`pill ${s.status === "available" ? "s-ok" : "s-review_range"}`}>{s.status}</span></div>
        <p className="muted">{s.purpose} · {s.required ? "Required for market report" : "Supplemental / later phase"}</p>
        <p><b>{fmt.n(s.file_count)}</b> file{ s.file_count === 1 ? "" : "s"}</p>
        {s.files.length > 0 && <details><summary>Show files</summary><ul className="source-files">
          {s.files.map((f) => <li key={f.path}><span>{f.path} · {fmt.n(f.size_bytes)} bytes</span></li>)}
        </ul></details>}
      </article>)}</div>
    </section>}</Loading>
  </>;
}
