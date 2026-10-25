"use client"

import { Skeleton } from "@chakra-ui/react"
import {
  getEvaluationCases,
  getEvaluationRun,
  getEvaluationRuns,
  startEvaluationRun,
  type EvaluationCase,
  type EvaluationCaseResult,
  type EvaluationCheckSet,
  type EvaluationDimension,
  type EvaluationRun,
} from "@/api/evaluations"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import {
  LuArrowLeft,
  LuArrowRight,
  LuCheck,
  LuDownload,
  LuFlaskConical,
  LuInfo,
  LuLoaderCircle,
  LuPlay,
  LuTriangleAlert,
  LuX,
} from "react-icons/lu"

const dimensions: { key: EvaluationDimension; label: string }[] = [
  { key: "answer", label: "Answer" },
  { key: "extraction", label: "Extraction" },
  { key: "evidence", label: "Evidence" },
  { key: "calculation", label: "Calculation" },
  { key: "uncertainty", label: "Uncertainty" },
]

function isActive(status?: string) {
  return status === "queued" || status === "running"
}

function DimensionMarks({ checks }: { checks?: EvaluationCheckSet }) {
  return (
    <span className="evaluation-marks" aria-label="Answer, extraction, evidence, calculation, uncertainty checks">
      {dimensions.map((dimension) => {
        const passed = checks?.[dimension.key]
        return (
          <span
            aria-label={`${dimension.label}: ${passed === null || passed === undefined ? "not evaluated" : passed ? "pass" : "fail"}`}
            className={passed === null || passed === undefined ? "is-pending" : passed ? "is-pass" : "is-fail"}
            key={dimension.key}
            title={`${dimension.label}: ${passed === null || passed === undefined ? "Not evaluated" : passed ? "Pass" : "Fail"}`}
          >
            {passed === null || passed === undefined ? "–" : passed ? <LuCheck aria-hidden="true" /> : <LuX aria-hidden="true" />}
          </span>
        )
      })}
    </span>
  )
}

function CaseBadge({ result }: { result?: EvaluationCaseResult }) {
  if (!result) return <span className="evaluation-result is-pending">Not run</span>
  const label = result.status === "evaluated"
    ? result.passed ? "Pass" : "Fail"
    : result.status === "blocked" ? "Blocked" : "Error"
  const tone = result.status === "evaluated"
    ? result.passed ? "is-pass" : "is-fail"
    : result.status === "blocked" ? "is-blocked" : "is-fail"
  return <span className={`evaluation-result ${tone}`}>{label}</span>
}

function DimensionBadge({ passed }: { passed: boolean | null | undefined }) {
  if (passed === null || passed === undefined) return <span className="evaluation-result is-pending">Not run</span>
  return <span className={`evaluation-result ${passed ? "is-pass" : "is-fail"}`}>{passed ? "Pass" : "Fail"}</span>
}

function evidenceContext(item: EvaluationCase) {
  return item.expected_evidence
    .map((source) => {
      const location = source.page
        ? `p.${source.page}`
        : `${source.sheet}!${source.cell}`
      return `${source.filename} · ${location}`
    })
    .filter((value, index, all) => all.indexOf(value) === index)
    .join("; ")
}

function runLabel(run: Pick<EvaluationRun, "id" | "status" | "created_at">) {
  const date = new Date(run.created_at).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
  return `${run.status === "completed" ? "Completed" : run.status} · ${date} · ${run.id.slice(0, 8)}`
}

function aggregateChecks(run?: EvaluationRun) {
  const evaluated = (run?.case_results ?? []).filter((item) => item.status === "evaluated")
  return dimensions.map((dimension) => ({
    ...dimension,
    passed: evaluated.filter((item) => item.checks[dimension.key] === true).length,
  }))
}

function EvaluationLoadingSkeleton() {
  return (
    <main className="evaluations-page" aria-busy="true">
      <header className="review-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace">Workspace</Link>
          <span aria-hidden="true">/</span>
          <strong>Evaluations</strong>
        </div>
        <div className="review-topbar-meta">
          <span className="evaluation-live-tag">Source-grounded evaluation</span>
          <span>Loading results…</span>
        </div>
      </header>
      <div className="evaluations-content">
        <span className="sr-only" role="status">Loading evaluation results…</span>
        <div className="evaluations-title-row">
          <div>
            <h1>Better answers. Measurable evidence.</h1>
            <p>Run source-backed cases through the current extraction, answer, and financial-year workflows.</p>
          </div>
          <Skeleton height="40px" width="145px" borderRadius="7px" />
        </div>
        <div className="evaluation-run-row" aria-hidden="true">
          <Skeleton height="40px" width="180px" borderRadius="7px" />
          <Skeleton height="13px" width="210px" />
          <Skeleton height="28px" width="175px" borderRadius="5px" ml="auto" />
        </div>
        <section className="evaluation-score-grid" aria-hidden="true">
          {Array.from({ length: 3 }, (_, index) => (
            <article className="evaluation-score-card" key={index}>
              <Skeleton height="12px" width={index === 1 ? "125px" : "105px"} />
              <Skeleton height="30px" width="78px" mt="18px" mb="12px" />
              <Skeleton height="12px" width={index === 2 ? "68%" : "82%"} mt="auto" />
            </article>
          ))}
        </section>
        <section className="evaluation-panel evaluation-dimensions" aria-hidden="true">
          <div className="evaluation-panel-heading">
            <div>
              <Skeleton height="15px" width="125px" mb="8px" />
              <Skeleton height="11px" width="min(460px, 80vw)" />
            </div>
          </div>
          <div className="evaluation-dimension-grid">
            {dimensions.map((dimension) => (
              <div className="evaluation-dimension" key={dimension.key}>
                <Skeleton height="12px" width="78px" />
                <Skeleton height="15px" width="38px" />
              </div>
            ))}
          </div>
        </section>
        <section className="evaluation-panel" aria-hidden="true">
          <div className="evaluation-panel-heading evaluation-cases-heading">
            <div>
              <Skeleton height="15px" width="105px" mb="8px" />
              <Skeleton height="11px" width="min(540px, 80vw)" />
            </div>
            <Skeleton height="28px" width="92px" borderRadius="5px" />
          </div>
          <div className="evaluation-table-scroll">
            <table className="evaluation-table">
              <thead><tr><th>Case &amp; question</th><th>Expected source</th><th>Result</th><th>A / X / E / C / U</th><th>Duration</th></tr></thead>
              <tbody>
                {Array.from({ length: 4 }, (_, index) => (
                  <tr key={index}>
                    <td><Skeleton height="13px" width={index === 1 ? "70%" : "88%"} /></td>
                    <td><Skeleton height="12px" width="82%" /></td>
                    <td><Skeleton height="22px" width="54px" borderRadius="5px" /></td>
                    <td><Skeleton height="14px" width="110px" /></td>
                    <td><Skeleton height="12px" width="36px" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  )
}

export function EvaluationsArea() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState("")
  const [notice, setNotice] = useState("")
  const casesQuery = useQuery({ queryKey: ["evaluation-cases"], queryFn: getEvaluationCases })
  const runsQuery = useQuery({
    queryKey: ["evaluation-runs"],
    queryFn: () => getEvaluationRuns(20),
    refetchInterval: (query) => query.state.data?.some((run) => isActive(run.status)) ? 2000 : false,
  })
  const activeId = selectedRunId || runsQuery.data?.[0]?.id || ""
  const runQuery = useQuery({
    queryKey: ["evaluation-run", activeId],
    queryFn: () => getEvaluationRun(activeId),
    enabled: Boolean(activeId),
    refetchInterval: (query) => isActive(query.state.data?.status) ? 2000 : false,
  })
  const startMutation = useMutation({
    mutationFn: startEvaluationRun,
    onSuccess: async (run) => {
      setSelectedRunId(run.id)
      setNotice("")
      await queryClient.invalidateQueries({ queryKey: ["evaluation-runs"] })
      await queryClient.invalidateQueries({ queryKey: ["evaluation-run", run.id] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Unable to start evaluation."),
  })

  const run = runQuery.data
  const catalog = casesQuery.data ?? []
  const caseResultMap = new Map((run?.case_results ?? []).map((item) => [item.case_id, item]))
  const checks = aggregateChecks(run)
  const evidenceChecks = checks.find((item) => item.key === "evidence")
  const passed = run?.passed_count ?? 0
  const evaluated = run?.evaluated_count ?? 0
  const blocked = run?.blocked_count ?? 0
  const errors = run?.error_count ?? 0
  const active = Boolean(runsQuery.data?.some((item) => isActive(item.status))) || startMutation.isPending
  const loadError = runQuery.error ?? casesQuery.error ?? runsQuery.error
  const isInitialLoading = !loadError && (
    casesQuery.isPending ||
    runsQuery.isPending ||
    Boolean(activeId && runQuery.isPending)
  )

  function exportRun() {
    if (!run) return
    const rows = [
      ["Case", "Question", "Case status", "Passed", "Answer", "Answer check", "Extraction check", "Evidence check", "Calculation check", "Uncertainty check"],
      ...run.case_results.map((result) => [
        result.case_id,
        result.case.question,
        result.status,
        result.passed === null ? "" : result.passed ? "Pass" : "Fail",
        result.answer?.answer ?? (result.metric_value ? `${result.metric_label}: ${result.metric_value} ${result.metric_unit ?? ""} · ${result.period_label ?? ""}` : result.error_message ?? ""),
        String(result.checks.answer ?? ""),
        String(result.checks.extraction ?? ""),
        String(result.checks.evidence ?? ""),
        String(result.checks.calculation ?? ""),
        String(result.checks.uncertainty ?? ""),
      ]),
    ]
    const csv = rows
      .map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
      .join("\n")
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `kuki-evaluation-${run.case_set_version}-${run.id.slice(0, 8)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  if (isInitialLoading) {
    return <EvaluationLoadingSkeleton />
  }

  return (
    <main className="evaluations-page">
      <header className="review-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace">Workspace</Link><span aria-hidden="true">/</span><strong>Evaluations</strong>
        </div>
        <div className="review-topbar-meta">
          <span className="evaluation-live-tag">Source-grounded evaluation</span>
          <span>{run ? new Date(run.created_at).toLocaleDateString() : "Dataset v1"}</span>
          <span className="help-mark" aria-label="Evaluation help">?</span>
        </div>
      </header>

      <div className="evaluations-content">
        <div className="evaluations-title-row">
          <div>
            <h1>Better answers. Measurable evidence.</h1>
            <p>Run source-backed cases through the current extraction, answer, and financial-year workflows.</p>
          </div>
          <button className="button button-primary" disabled={active} onClick={() => { setNotice(""); startMutation.mutate() }} type="button">
            {active ? <LuLoaderCircle className="spin" aria-hidden="true" /> : <LuPlay aria-hidden="true" />}
            {active ? "Evaluation running" : "Run evaluation"}
          </button>
        </div>

        {notice && <div className="evaluation-notice" role="alert"><LuTriangleAlert aria-hidden="true" /><p>{notice}</p><button aria-label="Dismiss notice" onClick={() => setNotice("")} type="button"><LuX aria-hidden="true" /></button></div>}
        {run?.status === "queued" && <div className="evaluation-notice" role="status"><LuInfo aria-hidden="true" /><p>The run is queued. The dispatcher will send it to the evaluation worker.</p></div>}
        {run?.status === "running" && <div className="evaluation-notice" role="status"><LuLoaderCircle className="spin" aria-hidden="true" /><p>{run.current_stage ?? "Evaluation running"} · {run.completed_count} of {run.case_count} cases saved · answer model {run.model_name ?? "not reported"}.</p></div>}
        {run?.status === "failed" && <div className="evaluation-notice" role="alert"><LuTriangleAlert aria-hidden="true" /><p>{run.error_message ?? "The evaluation runner failed."}</p></div>}

        <div className="evaluation-run-row">
          <label className="evaluation-select-wrap">
            <span className="sr-only">Saved evaluation run</span>
            <select aria-label="Saved evaluation run" disabled={!runsQuery.data?.length} onChange={(event) => setSelectedRunId(event.target.value)} value={activeId}>
              {runsQuery.data?.length
                ? runsQuery.data.map((item) => <option key={item.id} value={item.id}>{`${item.status} · ${new Date(item.created_at).toLocaleString()} · ${item.id.slice(0, 8)}`}</option>)
                : <option value="">No saved runs</option>}
            </select>
          </label>
          <span className="evaluation-run-meta">{run ? `${run.case_set_version} · ${run.case_count} cases · ${run.current_stage ?? run.model_name ?? "model not started"}` : `${catalog.length || "Source-backed"} cases · no run selected`}</span>
          <span className="evaluation-expected-tag">Live results · source verification enabled</span>
        </div>

        {(runQuery.isError || casesQuery.isError || runsQuery.isError) && <div className="evaluation-notice" role="alert"><LuTriangleAlert aria-hidden="true" /><p>Could not load evaluation data. {loadError instanceof Error ? loadError.message : "Please refresh the page."}</p></div>}

        <section className="evaluation-score-grid" aria-label="Evaluation summary">
          <article className="evaluation-score-card">
            <span>{run ? "Cases passing all dimensions" : "Latest evaluation"}</span>
            <strong>{run ? `${passed} / ${evaluated || "—"}` : "No run yet"}</strong>
            <p>{run ? `${evaluated ? `${Math.round((passed / evaluated) * 100)}% pass rate` : "No cases scored"} · ${blocked} blocked · ${errors} errors` : "Run the current pipeline to establish a real score."}</p>
          </article>
          <article className="evaluation-score-card is-highlight">
            <span>Evidence checks passed</span>
            <strong>{run ? `${evidenceChecks?.passed ?? 0} / ${evaluated || "—"}` : "—"}</strong>
            <p>Source locator and application verification must both match.</p>
          </article>
          <article className="evaluation-score-card">
            <span>Case coverage</span>
            <strong>{run ? `${run.completed_count} / ${run.case_count}` : catalog.length ? `${catalog.length} cases` : "Case pack"}</strong>
            <p>{run ? `${blocked} missing or unready documents · ${errors} answer errors` : "Each case is pinned to a source document and version."}</p>
          </article>
        </section>

        <section className="evaluation-panel evaluation-dimensions">
          <div className="evaluation-panel-heading"><div><h2>Dimension checks</h2><p>A case passes only when answer, extraction, evidence, calculation, and uncertainty checks pass.</p></div></div>
          <div className="evaluation-dimension-grid">
            {checks.map((dimension) => <div className="evaluation-dimension" key={dimension.key}><span>{dimension.label}</span><strong>{run ? `${dimension.passed} / ${evaluated || "—"}` : "Not run"}</strong></div>)}
          </div>
        </section>

        <section className="evaluation-panel">
          <div className="evaluation-panel-heading evaluation-cases-heading">
            <div><h2>Case results</h2><p>A / X / E / C / U = Answer / Extraction / Evidence / Calculation / Uncertainty · Scores come from this saved run.</p></div>
            <button className="evaluation-export" disabled={!run?.case_results.length} onClick={exportRun} type="button">Export run <LuDownload aria-hidden="true" /></button>
          </div>
          <div className="evaluation-table-scroll">
            <table className="evaluation-table">
              <thead><tr><th>Case &amp; question</th><th>Expected source</th><th>Result</th><th>A / X / E / C / U</th><th>Duration</th></tr></thead>
              <tbody>
                {(catalog.length ? catalog : run?.case_results.map((item) => item.case) ?? []).map((item) => {
                  const result = caseResultMap.get(item.id)
                  const href = `/workspace/evaluations/${item.id}${activeId ? `?run=${activeId}` : ""}`
                  return <tr key={item.id}>
                    <td><Link className="evaluation-case-link" href={href}><span>{item.id}</span><strong>{item.question}</strong><LuArrowRight aria-hidden="true" /></Link></td>
                    <td className="evaluation-context">{evidenceContext(item)}</td>
                    <td><CaseBadge result={result} /></td>
                    <td><DimensionMarks checks={result?.checks} /></td>
                    <td className="evaluation-context">{result?.duration_ms == null ? "—" : `${(result.duration_ms / 1000).toFixed(1)} s`}</td>
                  </tr>
                })}
                {!catalog.length && casesQuery.isLoading && <tr><td colSpan={5}>Loading the versioned case pack…</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <div className="evaluation-callouts">
          <aside className="evaluation-callout is-good"><LuInfo aria-hidden="true" /><div><strong>What a pass means</strong><p>The answer matched the case assertions, cited the expected source locations, and passed the backend’s quote or calculation checks.</p></div></aside>
          <aside className="evaluation-callout is-warning"><LuTriangleAlert aria-hidden="true" /><div><strong>Run limitations</strong><p>Cases use the uploaded assignment dataset. Blocked cases need their exact original files uploaded; each run freshly extracts those pinned files and does not measure performance on unseen documents.</p></div></aside>
        </div>
        <footer className="evaluation-footer"><span>KuKi / Environmental intelligence</span><span>{run ? `Case set ${run.case_set_version} · SHA ${run.case_set_hash.slice(0, 12)} · ${runLabel(run)}` : "No evaluation has run yet"}</span></footer>
      </div>
    </main>
  )
}

export function EvaluationDetailArea({ caseId }: { caseId: string }) {
  const [requestedRunId, setRequestedRunId] = useState("")
  useEffect(() => {
    setRequestedRunId(new URLSearchParams(window.location.search).get("run") ?? "")
  }, [])
  const casesQuery = useQuery({ queryKey: ["evaluation-cases"], queryFn: getEvaluationCases })
  const runsQuery = useQuery({
    queryKey: ["evaluation-runs"],
    queryFn: () => getEvaluationRuns(20),
    refetchInterval: (query) => query.state.data?.some((run) => isActive(run.status)) ? 2000 : false,
  })
  const selectedRunId = requestedRunId || runsQuery.data?.[0]?.id || ""
  const runQuery = useQuery({
    queryKey: ["evaluation-run", selectedRunId],
    queryFn: () => getEvaluationRun(selectedRunId),
    enabled: Boolean(selectedRunId),
    refetchInterval: (query) => isActive(query.state.data?.status) ? 2000 : false,
  })
  const caseDefinition = casesQuery.data?.find((item) => item.id === caseId)
  const result = runQuery.data?.case_results.find((item) => item.case_id === caseId)
  const cases = casesQuery.data ?? []
  const index = cases.findIndex((item) => item.id === caseId)
  const previous = cases[(index - 1 + cases.length) % cases.length]
  const next = cases[(index + 1) % cases.length]

  if (casesQuery.isLoading) return <main className="evaluations-page"><div className="evaluations-content"><p>Loading evaluation case…</p></div></main>
  if (!caseDefinition) {
    return <main className="evaluations-page"><header className="review-topbar"><div className="review-breadcrumb"><Link href="/workspace">Workspace</Link><span>/</span><Link href="/workspace/evaluations">Evaluations</Link><span>/</span><strong>Not found</strong></div></header><div className="evaluations-content"><section className="evaluation-panel evaluation-not-found"><h1>Evaluation case not found</h1><p>This case is not in the current source-backed pack.</p><Link className="button button-outline" href="/workspace/evaluations">All cases</Link></section></div></main>
  }

  const statusLabel = !result ? "Not run" : result.status === "evaluated" ? result.passed ? "Pass" : "Fail" : result.status === "blocked" ? "Blocked" : "Error"
  const checks = result?.checks
  const expectedLocations = caseDefinition.expected_evidence.map((item) => item.page ? `${item.filename} · p.${item.page}` : `${item.filename} · ${item.sheet}!${item.cell}`).join("; ")
  const answer = result?.answer
  const financialYearSummary = result?.financial_year_summary
  const financialYearMetric = financialYearSummary?.metrics.find((item) =>
    item.metric === "electricity" && item.value === result?.metric_value && item.unit === result?.metric_unit,
  )
  const financialYearNoDataMetrics = financialYearSummary?.metrics.filter((item) => item.status === "no_data") ?? []
  const financialYearSources = financialYearSummary?.sources ?? []

  return (
    <main className="evaluations-page">
      <header className="review-topbar">
        <div className="review-breadcrumb"><Link href="/workspace">Workspace</Link><span aria-hidden="true">/</span><Link href="/workspace/evaluations">Evaluations</Link><span aria-hidden="true">/</span><strong>{caseDefinition.id}</strong></div>
        <div className="review-topbar-meta"><span className="evaluation-live-tag">{runQuery.data?.case_set_version ?? "Source-grounded"}</span><span>{runQuery.data ? new Date(runQuery.data.created_at).toLocaleDateString() : "No saved run"}</span></div>
      </header>
      <div className="evaluations-content">
        <div className="evaluations-detail-title-row"><div><h1>{caseDefinition.id} · {caseDefinition.title}</h1><p>{caseDefinition.domain} · {caseDefinition.runner === "financial_year_summary" ? "Financial-Year Summary service" : "Production answer pipeline"}</p></div><Link className="button button-outline" href="/workspace/evaluations"><LuArrowLeft aria-hidden="true" /> All cases</Link></div>
        <div className="evaluation-detail-status-row">
          <span className={`evaluation-result ${result?.status === "evaluated" ? result.passed ? "is-pass" : "is-fail" : result?.status === "blocked" ? "is-blocked" : "is-pending"}`}>{statusLabel}</span>
          <span>Expected status: {caseDefinition.expected_status}</span>
          <nav className="evaluation-case-nav" aria-label="Evaluation cases">
            {previous && <Link href={`/workspace/evaluations/${previous.id}${selectedRunId ? `?run=${selectedRunId}` : ""}`}>← Previous</Link>}
            {next && <Link href={`/workspace/evaluations/${next.id}${selectedRunId ? `?run=${selectedRunId}` : ""}`}>Next case <LuArrowRight aria-hidden="true" /></Link>}
          </nav>
        </div>

        <section className="evaluation-detail-brief">
          <div><span>Question</span><h2>{caseDefinition.question}</h2><p>{caseDefinition.required_documents.join(" · ")}</p></div>
          <div><span>Expected source locations</span><p className="evaluation-expected-copy">{expectedLocations}</p><small>Evidence passes only when the production source verifier confirms the returned quote and locator.</small></div>
        </section>

        <section className="evaluation-answer-grid" aria-label="Evaluation answer">
          <article className="evaluation-answer-card is-improved">
            <div className="evaluation-answer-heading"><div><h2>Actual answer</h2><p>{answer?.model ?? runQuery.data?.model_name ?? "No model call recorded"}{result?.duration_ms != null ? ` · ${(result.duration_ms / 1000).toFixed(1)} s` : ""}{result?.answer_attempts ? ` · ${result.answer_attempts} answer attempt${result.answer_attempts === 1 ? "" : "s"}` : ""}</p></div><span className="evaluation-answer-label">{statusLabel}</span></div>
            {result?.status === "blocked" || result?.status === "error" ? <><p className="evaluation-expected-copy">{result.error_message}</p>{result.failure_stage || result.failure_type ? <p className="evaluation-expected-copy">Stage: {result.failure_stage ?? "unknown"}{result.failure_type ? ` · Error: ${result.failure_type}` : ""}{result.failure_attempts ? ` · Attempts: ${result.failure_attempts}` : ""}{result.retryable === true ? " · Retryable" : result.retryable === false ? " · Not retryable" : ""}</p> : null}{result.failure_diagnostic ? <p className="evaluation-expected-copy">Structured-output details: {result.failure_diagnostic}</p> : null}</> : financialYearSummary ? <><blockquote>FY {financialYearSummary.financial_year}: {result?.metric_value ?? "No usable value"}{result?.metric_unit ? ` ${result.metric_unit}` : ""} · {result?.period_label ?? "No period coverage"}</blockquote><p className="evaluation-expected-copy">{financialYearSummary.coverage_status} coverage · {result?.months_covered ?? 0} of 12 months recorded. Missing months remain blank and are not treated as zero.</p>{financialYearNoDataMetrics.length ? <p className="evaluation-expected-copy">{financialYearNoDataMetrics.map((item) => `${item.label}: No data (not zero)`).join(" · ")}</p> : null}{financialYearSummary.gaps.map((gap) => <p className="evaluation-empty-copy" key={gap}>{gap}</p>)}</> : <blockquote>{answer ? `“${answer.answer}”` : "This case has not run yet."}</blockquote>}
            {answer?.gaps.length ? <div className="evaluation-explanation is-negative"><LuTriangleAlert aria-hidden="true" /><div><strong>Gaps returned by the answer</strong><p>{answer.gaps.join(" · ")}</p></div></div> : null}
          </article>
          <article className="evaluation-answer-card">
            <div className="evaluation-answer-heading"><div><h2>Run provenance</h2><p>Persisted run snapshot</p></div><span className="evaluation-answer-label">{runQuery.data?.status ?? "No run"}</span></div>
            <p className="evaluation-provenance-line">Case set: <strong>{runQuery.data?.case_set_version ?? "—"}</strong></p>
            <p className="evaluation-provenance-line">Document version: <strong>{Object.values(result?.document_snapshot ?? {})[0]?.file_hash?.slice(0, 16) ?? "Not pinned"}</strong></p>
            <p className="evaluation-provenance-line">Fresh extraction: <strong>{Object.values(result?.document_snapshot ?? {})[0]?.extraction_model ?? "Not run"}{Object.values(result?.document_snapshot ?? {})[0]?.extraction_pipeline ? ` · ${Object.values(result?.document_snapshot ?? {})[0]?.extraction_pipeline}` : ""}</strong></p>
            {Object.values(result?.document_snapshot ?? {})[0]?.financial_year_extraction_run_id ? <p className="evaluation-provenance-line">FY summary source run: <strong>{Object.values(result?.document_snapshot ?? {})[0]?.financial_year_extraction_run_id?.slice(0, 16)}</strong></p> : null}
            <p className="evaluation-provenance-line">Extraction prompt SHA: <strong>{runQuery.data?.extraction_prompt_hash.slice(0, 16) ?? "—"}</strong></p>
            <p className="evaluation-provenance-line">Answer prompt SHA: <strong>{runQuery.data?.answer_prompt_hash.slice(0, 16) ?? "—"}</strong></p>
            <p className="evaluation-provenance-line">Run ID: <strong>{runQuery.data?.id ?? "—"}</strong></p>
            <div className="evaluation-explanation is-positive"><LuInfo aria-hidden="true" /><div><strong>Scoring method</strong><p>{caseDefinition.runner === "financial_year_summary" ? "Checks the production FY service against the pinned extraction result, monthly source cells, exact sum, and missing-month coverage." : "Checks the generated answer against deterministic value, unit, status, and location assertions plus source verification."} The case pack is hashed and saved with every run.</p></div></div>
          </article>
        </section>

        <section className="evaluation-panel evaluation-check-panel">
          <div className="evaluation-panel-heading"><div><h2>Per-dimension checks</h2><p>Extraction and answer quality are scored separately; a verified citation alone does not make an answer correct.</p></div></div>
          <div className="evaluation-table-scroll"><table className="evaluation-table evaluation-detail-table"><thead><tr><th>Dimension</th><th>What is checked</th><th>Result</th></tr></thead><tbody>
            {dimensions.map((dimension) => {
              const details = result?.check_details?.[dimension.key] ?? []
              return <tr key={dimension.key}><td>{dimension.label}</td><td>{dimension.key === "answer" ? "Expected reported values or required coverage behavior." : dimension.key === "extraction" ? "Expected facts and locators exist in the fresh extraction output." : dimension.key === "evidence" ? "Expected document and page or sheet cell, with a verified source quote." : dimension.key === "calculation" ? "Required calculation result is independently reproducible." : "Answer status and missing-evidence treatment match the case."}{details.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-800">{details.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}</td><td><DimensionBadge passed={checks?.[dimension.key]} /></td></tr>
            })}
          </tbody></table></div>
        </section>

        <div className="evaluation-detail-bottom-grid">
          <section className="evaluation-panel evaluation-evidence-panel">
            <div className="evaluation-panel-heading"><div><h2>{financialYearSummary ? "Financial-year source evidence" : "Returned evidence"}</h2><p>{financialYearSummary ? "Verified workbook facts used by the saved FY service result" : "Actual excerpts cited by the answer model"}</p></div></div>
            {answer?.evidence.length ? <div className="evaluation-returned-evidence">{answer.evidence.map((item) => <article key={item.id}><strong>{item.filename} · {item.locator_label}</strong><p>{item.quote}</p><span className={item.verified ? "is-verified" : "is-unverified"}>{item.verified ? "Source verified" : item.verification}</span></article>)}</div> : financialYearSources.length ? <div className="evaluation-returned-evidence">{financialYearSources.map((item, index) => { const locator = item.locator.sheet ? `${item.locator.sheet}!${item.locator.cell_range ?? ""}` : item.locator.page ? `p.${item.locator.page}` : "Source location unavailable"; return <article key={`${item.filename}-${locator}-${index}`}><strong>{item.filename} · {locator} · {item.treatment}</strong><p>{item.quote ?? item.value_text}</p><span className={item.verified ? "is-verified" : "is-unverified"}>{item.verified ? "Source verified" : item.reason}</span></article> })}</div> : <p className="evaluation-empty-copy">No answer evidence was recorded for this case.</p>}
            {answer?.calculations.length ? <div className="evaluation-calculation-list"><strong>Returned calculations</strong>{answer.calculations.map((item) => <p key={item.id}>{item.expression} = {item.result} {item.unit ?? ""} · {item.matches ? "reproduced" : "does not reproduce"}</p>)}</div> : financialYearMetric?.calculation ? <div className="evaluation-calculation-list"><strong>Financial-year calculation</strong><p>{financialYearMetric.calculation} · independently reconciled to the primary monthly sources</p></div> : null}
          </section>
          <aside className="evaluation-panel evaluation-limitations"><h2>Case limitations</h2><p>Passing this question confirms only these expected facts and source locations for the pinned document version.</p><p>Missing or failed source documents are marked blocked and are excluded from the pass-rate denominator.</p>{runQuery.error instanceof Error ? <p>{runQuery.error.message}</p> : null}</aside>
        </div>
        <footer className="evaluation-footer"><span>KuKi / Environmental intelligence</span><Link className="evaluation-source-link" href="/workspace/evaluations"><LuFlaskConical aria-hidden="true" /> Back to actual evaluation results</Link></footer>
      </div>
    </main>
  )
}
