"use client"

import {
  getFinancialYearSummary,
  type FinancialYearMetric,
  type FinancialYearSource,
  type FinancialYearSummary,
} from "@/api/documents"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import {
  LuArrowUpRight,
  LuCalendarDays,
  LuChevronDown,
  LuDownload,
  LuInfo,
  LuLoaderCircle,
  LuTriangleAlert,
} from "react-icons/lu"

function formatNumber(value: string | null) {
  if (value === null || value === "") return ""
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value.trim().replaceAll(",", ""))
  if (!match) return value
  const integer = match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  const fraction = match[3]?.slice(1).replace(/0+$/, "") ?? ""
  return `${match[1]}${integer}${fraction ? `.${fraction}` : ""}`
}

function dateLabel(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  })
}

function cardNote(metric: FinancialYearMetric) {
  const appendNote = (note: string) => metric.note ? `${note} · ${metric.note}` : note
  if (metric.value === null) {
    if (metric.status === "conflict") return "Conflicting values · No value selected"
    return metric.metric === "waste"
      ? "Not zero · No usable records"
      : "No usable source records · Not zero"
  }
  if (metric.status === "conflict") return appendNote("Partial total · Source conflict needs review")
  if (metric.method === "Calculated monthly sum") {
    return appendNote(`${metric.method} · ${metric.months_covered} of 12 months`)
  }
  if (metric.method === "Source-reported period value") {
    return appendNote(`Source-reported value · ${metric.months_covered} of 12 months covered`)
  }
  if (metric.status === "calculated") {
    return appendNote(`${metric.method} · ${metric.months_covered} of 12 months covered`)
  }
  return appendNote(`${metric.method} · ${metric.months_covered} of 12 months covered`)
}

function headlineRank(metric: FinancialYearMetric) {
  const name = `${metric.series ?? ""} ${metric.label}`
    .normalize("NFKC")
    .replace(/[_-]+/g, " ")
    .toLowerCase()
  if (/\btotal\s+(?:electricity\s+)?consumption\b|\bconsumption\s+total\b/.test(name)) return 5
  if (/\bunits?\s+consumed\b/.test(name)) return 4
  if (/\bnet\s+consumption\b/.test(name)) return 3
  if (/^\s*consumption\b/.test(name)) return 2
  return 0
}

function headlineMetrics(metrics: FinancialYearMetric[]) {
  const selected: FinancialYearMetric[] = []
  const coreResources = ["electricity", "water", "waste"]

  for (const resource of coreResources) {
    const groups = metrics.filter((metric) => metric.metric === resource)
    const byUnit = new Map<string, FinancialYearMetric[]>()
    for (const group of groups) {
      const unit = (group.unit ?? "").trim().toLowerCase()
      byUnit.set(unit, [...(byUnit.get(unit) ?? []), group])
    }

    for (const unitGroups of byUnit.values()) {
      const preferred = unitGroups
        .filter((metric) => metric.value !== null || metric.status === "conflict")
        .map((metric) => ({ metric, rank: headlineRank(metric) }))
        .filter(({ rank }) => rank > 0)
      if (preferred.length === 0) {
        selected.push(...unitGroups)
        continue
      }
      const bestRank = Math.max(...preferred.map(({ rank }) => rank))
      selected.push(...preferred.filter(({ rank }) => rank === bestRank).map(({ metric }) => metric))
    }
  }

  selected.push(
    ...metrics.filter(
      (metric) => !coreResources.includes(metric.metric) && (metric.value !== null || metric.status === "conflict"),
    ),
  )
  return selected
}

function sourceTreatment(source: FinancialYearSource) {
  if (source.treatment === "primary") return "Included in series total"
  if (source.treatment === "corroboration") return "Corroboration only"
  if (source.treatment === "supporting") return "Meter reading check"
  return "Excluded from total"
}

function locatorText(source: FinancialYearSource) {
  if (source.locator.page != null) return `p.${source.locator.page}`
  if (source.locator.sheet) {
    return `${source.locator.sheet}${source.locator.cell_range ? `!${source.locator.cell_range}` : ""}`
  }
  return "Source location unavailable"
}

function sourcePeriod(source: FinancialYearSource) {
  if (!source.period_start && !source.period_end) return "Period not stated"
  if (source.period_start === source.period_end) return source.period_start
  return `${source.period_start ?? "Start not stated"} – ${source.period_end ?? "End not stated"}`
}

function csvCell(value: string | number | null | undefined) {
  const text = value == null ? "" : String(value)
  return `"${text.replaceAll('"', '""')}"`
}

function downloadSummary(summary: FinancialYearSummary | undefined) {
  if (!summary) return
  const rows: (string | number | null)[][] = [
    ["Financial year", summary.financial_year],
    ["Organisation", summary.organisation_options.find((item) => item.value === summary.organisation)?.label ?? ""],
    ["Scope starts", summary.financial_year_start],
    ["Scope ends", summary.financial_year_end],
    ["Scoped documents", summary.documents.filter((item) => item.selected).map((item) => item.filename).join("; ")],
    [],
    ["Metric", "Series", "Unit", "Value", "Coverage", "Method", "Calculation", "Note"],
    ...summary.metrics.map((metric) => [
      metric.label,
      metric.series,
      metric.unit,
      metric.value,
      metric.period_label,
      metric.method,
      metric.calculation,
      metric.note,
    ]),
    [],
    ["Monthly coverage", "Series", "Unit", "Month", "Monthly value", "Coverage"],
    ...summary.metrics.flatMap((metric) => metric.months.map((month) => [
      metric.label,
      metric.series,
      metric.unit,
      month.label,
      month.value,
      month.covered ? "Covered" : "No data",
    ])),
    [],
    ["Source", "Fact", "Metric", "Reported value", "Unit", "Period start", "Period end", "Location", "Treatment", "Reason"],
    ...summary.sources.map((source) => [
      source.filename,
      source.label,
      source.metric,
      source.value_text,
      source.unit,
      source.period_start,
      source.period_end,
      locatorText(source),
      sourceTreatment(source),
      source.reason,
    ]),
    [],
    ["Gap or assumption"],
    ...summary.gaps.map((gap) => [gap]),
    [],
    ["Excluded document", "Organisation", "Status", "Reason"],
    ...summary.excluded_documents.map((document) => [
      document.filename,
      document.organisation,
      document.status,
      document.reason,
    ]),
  ]
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n")
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
  const link = document.createElement("a")
  link.href = url
  link.download = `financial-year-${summary.financial_year}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

function MetricCard({
  metric,
  accent,
}: {
  metric: FinancialYearMetric
  accent: "green" | "amber" | "ink"
}) {
  return (
    <article className={`fy-kpi-card is-${accent}`}>
      <p>{metric.label}{metric.series ? ` · ${metric.series}` : ""}{metric.period_label !== "No usable records" ? ` · ${metric.period_label}` : " · No usable records"}</p>
      <strong>
        {metric.value === null
          ? metric.status === "conflict" ? "Conflicting data" : "No data"
          : <>{formatNumber(metric.value)}{metric.unit ? ` ${metric.unit}` : ""}</>}
      </strong>
      <span>{cardNote(metric)}</span>
    </article>
  )
}

function CoverageGrid({ metrics }: { metrics: FinancialYearMetric[] }) {
  const electricityValues = metrics
    .filter((metric) => metric.metric === "electricity")
    .flatMap((metric) => metric.months.flatMap((month) => month.value ? [Number(month.value)] : []))
  const maximumElectricity = Math.max(...electricityValues, 0)

  return (
    <section className="fy-panel fy-coverage-panel" aria-labelledby="fy-coverage-title">
      <div className="fy-panel-heading">
        <div>
          <h2 id="fy-coverage-title">Monthly evidence coverage</h2>
          <p>Filled cells show period coverage. A covered quarter does not imply a monthly quantity.</p>
        </div>
        <Link className="fy-text-link" href="/workspace/documents">
          Inspect evidence <LuArrowUpRight aria-hidden="true" />
        </Link>
      </div>

      <div className="fy-coverage-legend" aria-label="Coverage legend">
        <span className="fy-legend-recorded">Recorded</span>
        <span className="fy-legend-empty">— No data</span>
        <span>Missing periods are never treated as zero.</span>
      </div>

      <div className="fy-month-grid" role="table" aria-label="Monthly evidence by resource">
        <div className="fy-month-header" role="row">
          <span aria-hidden="true" />
          <div className="fy-month-cells">
            {(metrics[0]?.months ?? []).map((month) => <span key={month.label}>{month.label}</span>)}
          </div>
        </div>
        {metrics.map((metric) => (
          <div className="fy-month-row" role="row" key={`${metric.metric}-${metric.series ?? "none"}-${metric.unit ?? "none"}`}>
            <div className="fy-resource-label" role="rowheader">
              <strong>{metric.label}{metric.series ? ` · ${metric.series}` : ""}</strong>
              <span>{metric.unit ? `${metric.unit} / month` : "No unit available"}</span>
            </div>
            <div className="fy-month-cells">
              {metric.months.map((month) => {
                const value = month.value ? Number(month.value) : 0
                const height = maximumElectricity > 0 && metric.metric === "electricity" && value > 0
                  ? `${Math.max(28, (value / maximumElectricity) * 100)}%`
                  : "0%"
                return (
                  <div
                    className={`fy-month-cell ${metric.metric === "electricity" ? "is-electricity" : "is-coverage"} ${month.covered ? "is-covered" : ""} ${month.value ? "has-value" : ""}`}
                    role="cell"
                      key={`${metric.metric}-${metric.series ?? "none"}-${month.label}`}
                    aria-label={`${metric.label}, ${month.label}: ${month.value ? `${formatNumber(month.value)} ${metric.unit ?? ""}` : month.covered ? "period covered, monthly amount unavailable" : "no data"}`}
                  >
                    <span className="fy-month-amount">
                      {month.value ? formatNumber(month.value) : month.covered ? "Covered" : "—"}
                    </span>
                    {metric.metric === "electricity" && (
                      <div className="fy-month-bar-track">
                        <div className="fy-month-bar" style={{ height }} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="fy-coverage-footnote">
        {metrics.find((metric) => metric.metric === "water" && metric.value !== null)?.note ??
          "Period coverage is shown from the dates stated in each source."}
      </p>
    </section>
  )
}

function SourcesTable({ sources }: { sources: FinancialYearSource[] }) {
  return (
    <section className="fy-panel fy-source-panel" aria-labelledby="fy-source-title">
      <div className="fy-panel-heading">
        <div>
          <h2 id="fy-source-title">How these totals were built</h2>
          <p>Named series stay separate. The headline uses an explicit total series when the source provides one.</p>
        </div>
      </div>
      {sources.length === 0 ? (
        <div className="fy-empty-inline">No source facts are available for this scope.</div>
      ) : (
        <div className="fy-table-scroll">
          <table className="fy-source-table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Primary evidence</th>
                <th>Method and source value</th>
                <th>Treatment</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.fact_id}>
                  <td>
                    <strong>{source.metric ? source.metric[0].toUpperCase() + source.metric.slice(1) : "Source fact"}</strong>
                    <span className="fy-source-locator">{source.label}</span>
                  </td>
                  <td>
                    <Link className="fy-source-document" href={`/workspace/documents/${source.document_id}?fact=${source.fact_id}`}>
                      {source.filename}
                    </Link>
                    <span className="fy-source-locator" title={source.quote ?? undefined}>
                      {locatorText(source)} · {sourcePeriod(source)}{source.verified ? " · Source verified" : " · Review source"}
                    </span>
                  </td>
                  <td>
                    <span>{source.value_text || `${formatNumber(source.value)} ${source.unit ?? ""}`}</span>
                    <span className="fy-source-locator">{source.reason}</span>
                  </td>
                  <td>
                    <span className={`fy-treatment is-${source.treatment}`}>
                      {sourceTreatment(source)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function FinancialYearArea() {
  const [financialYear, setFinancialYear] = useState("")
  const [organisation, setOrganisation] = useState("")
  const [documentIds, setDocumentIds] = useState<string[] | null>(null)
  const stableDocumentIds = useMemo(
    () => documentIds === null ? null : [...documentIds].sort(),
    [documentIds],
  )
  const summaryQuery = useQuery({
    queryKey: ["financial-year-summary", financialYear, organisation, stableDocumentIds],
    queryFn: () => getFinancialYearSummary({
      financialYear: financialYear || undefined,
      organisation: organisation || undefined,
      documentIds: stableDocumentIds,
    }),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.documents.some((document) => document.status === "processing" || document.status === "pending")
        ? 5000
        : false,
  })
  const summary = summaryQuery.data

  useEffect(() => {
    if (!summary) return
    if (!financialYear) setFinancialYear(summary.financial_year)
    if (!organisation && summary.organisation) setOrganisation(summary.organisation)
  }, [financialYear, organisation, summary])

  const coreMetrics = useMemo(() => {
    if (!summary) return []
    return headlineMetrics(summary.metrics)
  }, [summary])

  const onDocumentToggle = (id: string, checked: boolean) => {
    const current = documentIds ?? summary?.selected_document_ids ?? []
    const next = checked
      ? [...new Set([...current, id])]
      : current.filter((documentId) => documentId !== id)
    setDocumentIds(next)
  }

  const selectedOrganisationLabel = summary
    ? summary.organisation_options.find((option) => option.value === summary.organisation)?.label ?? "All organisations"
    : "All organisations"

  return (
    <main className="fy-page">
      <header className="fy-topbar">
        <div className="fy-breadcrumb">
          <Link href="/workspace">Workspace</Link>
          <span aria-hidden="true">/</span>
          <strong>Financial-Year Summary</strong>
        </div>
        <div className="fy-topbar-meta">
          <span className="fy-data-badge"><LuCalendarDays aria-hidden="true" /> Source-backed view</span>
          <span>Indian financial year</span>
        </div>
      </header>

      <div className="fy-content">
        <div className="fy-title-row">
          <div>
            <h1>A financial year, with the gaps visible.</h1>
            <p>
              {summary
                ? `Indian financial year · ${dateLabel(summary.financial_year_start)} – ${dateLabel(summary.financial_year_end)}`
                : "Indian financial year · 1 April – 31 March"}
            </p>
          </div>
          <button
            className="button button-outline"
            type="button"
            disabled={!summary}
            onClick={() => downloadSummary(summary)}
          >
            <LuDownload aria-hidden="true" /> Export summary
          </button>
        </div>

        {summary && (
          <div className="fy-filter-row">
            <label className="fy-select-wrap">
              <span className="sr-only">Financial year</span>
              <select
                value={financialYear || summary.financial_year}
                onChange={(event) => setFinancialYear(event.target.value)}
              >
                {summary.financial_year_options.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <LuChevronDown aria-hidden="true" />
            </label>
            <label className="fy-select-wrap fy-organisation-select">
              <span className="sr-only">Organisation</span>
              <select
                value={organisation || summary.organisation || ""}
                onChange={(event) => {
                  setOrganisation(event.target.value)
                  setDocumentIds(null)
                }}
              >
                {summary.organisation_options.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <LuChevronDown aria-hidden="true" />
            </label>
            <details className="fy-document-filter">
              <summary>
                {(documentIds ?? summary.selected_document_ids).length} scoped documents
                <LuChevronDown aria-hidden="true" />
              </summary>
              <div className="fy-document-menu">
                <div className="fy-document-menu-header">
                  <strong>Documents in this scope</strong>
                  <button type="button" onClick={() => setDocumentIds(summary.documents.map((item) => item.id))}>Select all</button>
                </div>
                {summary.documents.map((document) => (
                  <label className="fy-document-option" key={document.id}>
                    <input
                      type="checkbox"
                      checked={(documentIds ?? summary.selected_document_ids).includes(document.id)}
                      onChange={(event) => onDocumentToggle(document.id, event.target.checked)}
                    />
                    <span>
                      <strong>{document.filename}</strong>
                      <small>{document.status === "success" ? "Ready" : document.status}</small>
                    </span>
                  </label>
                ))}
                {summary.documents.length === 0 && <p>No documents for this organisation.</p>}
              </div>
            </details>
            <span className="fy-scope-count">
              {summary.primary_source_count} primary sources · {summary.corroborating_source_count} corroborating
            </span>
            <span className={`fy-coverage-badge is-${summary.coverage_status}`}>
              {summary.coverage_status === "complete" ? "Complete coverage" : summary.coverage_status === "no_data" ? "No usable data" : "Partial coverage"}
            </span>
          </div>
        )}

        {summaryQuery.isPending && (
          <div className="fy-state" role="status">
            <LuLoaderCircle className="spin" aria-hidden="true" /> Loading financial-year evidence…
          </div>
        )}
        {summaryQuery.isError && (
          <div className="fy-state is-error" role="alert">
            <LuTriangleAlert aria-hidden="true" /> {summaryQuery.error.message}
          </div>
        )}
        {summary && (
          <>
            {summary.documents.length === 0 && summary.organisation_options.length === 0 ? (
              <section className="fy-empty-state">
                <span><LuInfo aria-hidden="true" /></span>
                <h2>No documents to summarize yet</h2>
                <p>Upload utility bills, consumption workbooks, or waste records to build a source-backed financial-year view.</p>
                <Link className="button button-primary" href="/workspace/upload">Upload documents</Link>
              </section>
            ) : (
              <>
                <section className="fy-kpi-grid" aria-label="Financial-year resource totals">
                  {coreMetrics.map((metric) => (
                    <MetricCard
                      key={`${metric.metric}-${metric.series ?? ""}-${metric.unit ?? ""}`}
                      metric={metric}
                      accent={metric.metric === "water" ? "amber" : metric.metric === "waste" ? "ink" : "green"}
                    />
                  ))}
                </section>

                <CoverageGrid metrics={coreMetrics} />
                <SourcesTable sources={summary.sources} />

                <div className="fy-bottom-grid">
                  <section className="fy-notice is-warning" aria-labelledby="fy-gaps-title">
                    <div className="fy-notice-title"><LuTriangleAlert aria-hidden="true" /><strong id="fy-gaps-title">Gaps &amp; assumptions</strong></div>
                    {summary.gaps.length ? (
                      <ul>{summary.gaps.map((gap, index) => <li key={`${index}-${gap}`}>{gap}</li>)}</ul>
                    ) : <p>No gaps were identified in the selected source records.</p>}
                  </section>
                  <section className="fy-notice is-muted" aria-labelledby="fy-excluded-title">
                    <div className="fy-notice-title"><LuInfo aria-hidden="true" /><strong id="fy-excluded-title">Excluded from this scope</strong></div>
                    {summary.excluded_documents.length ? (
                      <ul>{summary.excluded_documents.map((document) => (
                        <li key={document.id}>
                          <Link href={`/workspace/documents/${document.id}`}>{document.filename}</Link>: {document.reason}
                        </li>
                      ))}</ul>
                    ) : <p>No other documents were excluded from this scope. {selectedOrganisationLabel}.</p>}
                  </section>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </main>
  )
}
