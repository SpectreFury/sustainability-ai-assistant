"use client"

import {
  getDocuments,
  getDocumentReview,
  markDocumentReviewed,
  saveDocumentReviewFacts,
  type DocumentReview,
  type ReviewFact,
  type ReviewFactUpdate,
  type ReviewSegment,
} from "@/api/documents"
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState, type ReactNode } from "react"
import {
  LuArrowLeft,
  LuCheck,
  LuCheckCheck,
  LuExternalLink,
  LuFileSpreadsheet,
  LuInfo,
  LuLoaderCircle,
  LuSave,
  LuTriangleAlert,
} from "react-icons/lu"

type FactDraft = { label: string; value_text: string }
type DraftMap = Record<string, FactDraft>
type CheckResult = {
  title: string
  expression: string
  result: string
  unit: string | null
  matches: boolean
}

function initialDrafts(facts: ReviewFact[]): DraftMap {
  return Object.fromEntries(
    facts.map((fact) => [fact.id, { label: fact.label, value_text: fact.value_text }]),
  )
}

function locatorText(fact: ReviewFact) {
  if (fact.locator.page != null) return `p.${fact.locator.page} · Source`
  if (fact.locator.sheet) {
    return `${fact.locator.sheet}${fact.locator.cell_range ? `!${fact.locator.cell_range}` : ""}`
  }
  return "Source"
}

function shortPeriod(start: string | null, end: string | null) {
  if (!start && !end) return "Period not stated"
  const format = (value: string) =>
    new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    })
  if (start && end && start !== end) return `${format(start)} – ${format(end)}`
  return format(start ?? end ?? "")
}

function periodsOverlap(
  leftStart: string | null,
  leftEnd: string | null,
  rightStart: string | null,
  rightEnd: string | null,
) {
  return (
    (!leftEnd || !rightStart || leftEnd >= rightStart) &&
    (!rightEnd || !leftStart || rightEnd >= leftStart)
  )
}

function dateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function uniqueNumber(value: string): number | null {
  const matches = value.match(/(?<![\w/])[+-]?\d[\d,]*(?:\.\d+)?/g)
  if (!matches || matches.length !== 1) return null
  const number = Number(matches[0].replaceAll(",", ""))
  return Number.isFinite(number) ? number : null
}

function numberFor(fact: ReviewFact, drafts: DraftMap) {
  const draft = drafts[fact.id]
  if (draft?.value_text !== fact.value_text) return uniqueNumber(draft?.value_text ?? "")
  return fact.value_number == null ? uniqueNumber(fact.value_text) : Number(fact.value_number)
}

function factSearchText(fact: ReviewFact) {
  return `${fact.key} ${fact.label}`.toLowerCase().replaceAll("_", " ")
}

function compatibleUnits(facts: ReviewFact[]) {
  const units = facts.map((fact) => fact.unit?.trim().toLowerCase() ?? "")
  return Boolean(units[0]) && units.every((unit) => unit === units[0])
}

function validationChecks(facts: ReviewFact[], drafts: DraftMap): CheckResult[] {
  const checks: CheckResult[] = []
  const previousReadings = facts.filter((fact) => {
    const text = factSearchText(fact)
    return fact.category === "meter_reading" && text.includes("previous")
  })
  const currentReadings = facts.filter((fact) => {
    const text = factSearchText(fact)
    return fact.category === "meter_reading" && text.includes("current")
  })
  const multipliers = facts.filter((fact) => {
    const text = factSearchText(fact)
    return text.includes("multiplier") || text.includes("multiplying factor")
  })
  const consumptions = facts.filter((fact) => fact.category === "consumption")

  if (
    previousReadings.length === 1 &&
    currentReadings.length === 1 &&
    multipliers.length === 1 &&
    consumptions.length === 1
  ) {
    const [previous] = previousReadings
    const [current] = currentReadings
    const [multiplier] = multipliers
    const [consumption] = consumptions
    const compatibleMetric =
      previous.metric === current.metric && current.metric === consumption.metric
    const compatibleReadingUnits =
      Boolean(previous.unit && previous.unit === current.unit && current.unit === consumption.unit)
    const previousValue = numberFor(previous, drafts)
    const currentValue = numberFor(current, drafts)
    const multiplierValue = numberFor(multiplier, drafts)
    const consumptionValue = numberFor(consumption, drafts)
    if (
      compatibleMetric &&
      compatibleReadingUnits &&
      previousValue != null &&
      currentValue != null &&
      multiplierValue != null &&
      consumptionValue != null
    ) {
      const calculated = (currentValue - previousValue) * multiplierValue
      checks.push({
        title: "Consumption agrees with meter readings",
        expression: `(${previousValue.toLocaleString()} → ${currentValue.toLocaleString()}) × ${multiplierValue.toLocaleString()}`,
        result: calculated.toLocaleString(undefined, { maximumFractionDigits: 4 }),
        unit: consumption.unit,
        matches: Math.abs(calculated - consumptionValue) <= 0.005,
      })
    }
  }

  const currentCharges = facts.filter((fact) =>
    factSearchText(fact).includes("current charges"),
  )
  const arrears = facts.filter((fact) => factSearchText(fact).includes("arrears"))
  const payable = facts.filter((fact) => {
    const text = factSearchText(fact)
    return text.includes("total payable") || text.includes("amount payable")
  })
  if (
    currentCharges.length === 1 &&
    arrears.length === 1 &&
    payable.length === 1 &&
    compatibleUnits([currentCharges[0], arrears[0], payable[0]])
  ) {
    const chargesValue = numberFor(currentCharges[0], drafts)
    const arrearsValue = numberFor(arrears[0], drafts)
    const payableValue = numberFor(payable[0], drafts)
    const costMetrics = [currentCharges[0], arrears[0], payable[0]].map(
      (fact) => fact.metric,
    )
    if (
      chargesValue != null &&
      arrearsValue != null &&
      payableValue != null &&
      costMetrics.every((metric) => metric === "cost")
    ) {
      const calculated = chargesValue + arrearsValue
      checks.push({
        title: "Current charges + arrears",
        expression: `${chargesValue.toLocaleString()} + ${arrearsValue.toLocaleString()}`,
        result: calculated.toLocaleString(undefined, { maximumFractionDigits: 2 }),
        unit: currentCharges[0].unit,
        matches: Math.abs(calculated - payableValue) <= 0.005,
      })
    }
  }
  return checks
}

function sourceSegment(
  fact: ReviewFact | null,
  segments: ReviewSegment[],
): ReviewSegment | null {
  if (!fact) return null
  if (fact.locator.sheet) {
    const rangeStart = fact.locator.cell_range?.split(":")[0]
    return (
      segments.find((segment) =>
        segment.locator.sheet === fact.locator.sheet &&
        (segment.locator.cell_range === fact.locator.cell_range ||
          (rangeStart != null && Object.hasOwn(segment.cells ?? {}, rangeStart))),
      ) ??
      segments.find((segment) => segment.locator.sheet === fact.locator.sheet) ??
      null
    )
  }
  return (
    segments.find((segment) =>
      fact.locator.page != null && segment.locator.page === fact.locator.page,
    ) ?? null
  )
}

function highlightedSource(text: string, quote: string | null): ReactNode {
  if (!quote) return text
  const start = text.indexOf(quote)
  if (start < 0) return text
  return (
    <>
      {text.slice(0, start)}
      <mark>{text.slice(start, start + quote.length)}</mark>
      {text.slice(start + quote.length)}
    </>
  )
}

function SpreadsheetCells({ segment }: { segment: ReviewSegment | null }) {
  const cells = Object.entries(segment?.cells ?? {}).sort(([left], [right]) =>
    left.localeCompare(right, undefined, { numeric: true }),
  )
  if (!cells.length) {
    return <p className="review-preview-empty">No spreadsheet cells are available for this location.</p>
  }
  return (
    <div className="review-cell-preview">
      {cells.slice(0, 80).map(([cell, value]) => (
        <div key={cell}>
          <code>{cell}</code>
          <span>{String(value)}</span>
        </div>
      ))}
      {cells.length > 80 && <p>Showing the first 80 cells in this source range.</p>}
    </div>
  )
}

function EvidencePanel({
  review,
  fact,
  page,
  onPageChange,
}: {
  review: DocumentReview
  fact: ReviewFact | null
  page: number
  onPageChange: (page: number) => void
}) {
  const [tab, setTab] = useState<"preview" | "text">("preview")
  const isPdf = review.filename.toLowerCase().endsWith(".pdf")
  const selectedSegment = sourceSegment(fact, review.segments)
  const segment = isPdf
    ? review.segments.find((item) => item.locator.page === page) ?? selectedSegment
    : selectedSegment
  const selectedQuote = fact?.locator.page == null || fact.locator.page === page
    ? fact?.quote ?? null
    : null
  const sheetName = fact?.locator.sheet
  const pages = Array.from(
    { length: Math.max(review.page_count ?? 1, 1) },
    (_, index) => index + 1,
  )

  return (
    <section className="review-card review-evidence" aria-label="Source evidence">
      <div className="review-card-heading">
        <h2>Source evidence</h2>
        {isPdf ? (
          <label className="review-page-select">
            <span className="sr-only">Select PDF page</span>
            <select value={page} onChange={(event) => onPageChange(Number(event.target.value))}>
              {pages.map((pageNumber) => (
                <option key={pageNumber} value={pageNumber}>
                  Page {pageNumber} of {pages.length}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="review-locator-pill">{sheetName ?? "Workbook"}</span>
        )}
      </div>

      <div className="review-tabs" role="tablist" aria-label="Evidence view">
        <button
          className={tab === "preview" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={tab === "preview"}
          onClick={() => setTab("preview")}
        >
          {isPdf ? "PDF preview" : "Workbook preview"}
        </button>
        <button
          className={tab === "text" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={tab === "text"}
          onClick={() => setTab("text")}
        >
          Source text
        </button>
      </div>

      {tab === "preview" && isPdf && review.file_url && (
        <iframe
          key={`${review.file_url}-${page}`}
          className="review-pdf-frame"
          title={`Preview of ${review.filename}, page ${page}`}
          src={`${review.file_url}#page=${page}&toolbar=0&navpanes=0`}
        />
      )}
      {tab === "preview" && isPdf && !review.file_url && (
        <div className="review-preview-empty">
          Original PDF preview is unavailable. Use the source text below to review the cited page.
        </div>
      )}
      {tab === "preview" && !isPdf && <SpreadsheetCells segment={segment} />}
      {tab === "text" && (
        <div className="review-source-text">
          {fact?.quote && (
            <blockquote>
              <strong>Selected fact</strong>
              <span>{fact.quote}</span>
            </blockquote>
          )}
          {segment?.scanned && (
            <p className="review-scan-note">
              This page is marked as scanned; its text could not be independently checked.
            </p>
          )}
          {segment?.text ? (
            <pre>{highlightedSource(segment.text, selectedQuote)}</pre>
          ) : (
            <p className="review-preview-empty">
              No source text is available for the selected location.
            </p>
          )}
        </div>
      )}

      <div className="review-preview-footer">
        <span>{isPdf ? `Page ${page}` : fact ? locatorText(fact) : "Select a fact to inspect its source"}</span>
        {review.file_url && (
          <a href={review.file_url} target="_blank" rel="noreferrer">
            Original file <LuExternalLink aria-hidden="true" />
          </a>
        )}
      </div>
      {fact && (
        <div className={`review-source-verification ${fact.verified ? "is-good" : "is-warning"}`}>
          {fact.verified ? <LuCheck aria-hidden="true" /> : <LuTriangleAlert aria-hidden="true" />}
          <span>{fact.verification || (fact.verified ? "Source location checked" : "Review the cited source")}</span>
        </div>
      )}
      <div className="review-evidence-hint">
        <LuInfo aria-hidden="true" />
        <span>Source values are preserved separately from reviewer edits.</span>
      </div>
    </section>
  )
}

function ValidationCard({ checks, issues }: { checks: CheckResult[]; issues: string[] }) {
  return (
    <section className="review-card review-validation">
      <div className="review-section-title">
        <div>
          <h2>Validation &amp; calculations</h2>
          <p>Derived checks are shown separately from source-reported facts.</p>
        </div>
      </div>
      {checks.length === 0 && issues.length === 0 && (
        <p className="review-no-checks">No bill arithmetic checks could be formed from these extracted fields.</p>
      )}
      {checks.map((check) => (
        <div className="review-check-row" key={check.title}>
          <div>
            <strong>{check.title}</strong>
            <p>
              {check.expression} = {check.result}{check.unit ? ` ${check.unit}` : ""}
            </p>
            {check.matches && <span className="review-check-detail">Calculated and reported values agree.</span>}
            {!check.matches && <span className="review-check-detail is-warning">Calculated and reported values differ.</span>}
          </div>
          <span className={`review-check-badge ${check.matches ? "is-good" : "is-warning"}`}>
            {check.matches ? "Match" : "Review"}
          </span>
        </div>
      ))}
      {issues.length > 0 && (
        <div className="review-issues">
          <strong><LuTriangleAlert aria-hidden="true" /> Needs a closer look</strong>
          <ul>{issues.map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}</ul>
        </div>
      )}
    </section>
  )
}

function RelatedSpreadsheetCard({
  documents,
}: {
  documents: { document: DocumentReview; facts: ReviewFact[] }[]
}) {
  if (documents.length === 0) return null
  return (
    <section className="review-card review-related">
      <div className="review-related-heading">
        <div>
          <h2>Related spreadsheet evidence</h2>
          <p>Same named organisation and matching metric. Check scope before comparing.</p>
        </div>
        <LuFileSpreadsheet aria-hidden="true" />
      </div>
      {documents.map(({ document, facts }) => (
        <div className="review-related-document" key={document.id}>
          <div className="review-related-file">
            <strong>{document.filename}</strong>
            {document.file_url && (
              <a href={document.file_url} target="_blank" rel="noreferrer">
                Open workbook <LuExternalLink aria-hidden="true" />
              </a>
            )}
          </div>
          <div className="review-related-facts">
            {facts.slice(0, 5)
              .map((fact) => (
                <div key={fact.id}>
                  <span>{fact.label}{fact.period_start ? ` · ${shortPeriod(fact.period_start, fact.period_end)}` : ""}</span>
                  <strong>{fact.value_text}</strong>
                  <small>{fact.locator.sheet}{fact.locator.cell_range ? `!${fact.locator.cell_range}` : ""}</small>
                </div>
              ))}
          </div>
        </div>
      ))}
    </section>
  )
}

export function DocumentReviewArea({ documentId }: { documentId: string }) {
  const queryClient = useQueryClient()
  const queryKey = ["document-review", documentId]
  const reviewQuery = useQuery({
    queryKey,
    queryFn: () => getDocumentReview(documentId),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data && ["pending", "processing"].includes(query.state.data.status)
        ? 3000
        : false,
  })
  const review = reviewQuery.data
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: getDocuments,
    enabled: review?.status === "success" && Boolean(review.organisation),
    retry: false,
  })
  const workbookDocuments = (documentsQuery.data ?? [])
    .filter(
      (document) =>
        document.id !== documentId &&
        document.status === "success" &&
        document.filename.toLowerCase().endsWith(".xlsx"),
    )
    .slice(0, 8)
  const workbookQueries = useQueries({
    queries: workbookDocuments.map((document) => ({
      queryKey: ["document-review", document.id],
      queryFn: () => getDocumentReview(document.id),
      retry: false,
      staleTime: 60_000,
    })),
  })
  const relatedWorkbooks = workbookQueries
    .map((query) => query.data)
    .flatMap((candidate) => {
      if (!review?.organisation || !candidate?.organisation) return []
      if (candidate.organisation.trim().toLowerCase() !== review.organisation.trim().toLowerCase()) return []
      const metrics = new Set(
        review.facts
          .filter((fact) => fact.category === "consumption" && fact.metric)
          .map((fact) => fact.metric),
      )
      const facts = candidate.facts.filter(
        (fact) =>
          fact.category === "consumption" &&
          fact.metric != null &&
          metrics.has(fact.metric) &&
          periodsOverlap(
            review.period_start,
            review.period_end,
            fact.period_start,
            fact.period_end,
          ),
      )
      return facts.length > 0 ? [{ document: candidate, facts }] : []
    })
  const [drafts, setDrafts] = useState<DraftMap>({})
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [manualPage, setManualPage] = useState<number | null>(null)

  const dirtyFacts = useMemo<ReviewFactUpdate[]>(() => {
    if (!review) return []
    return review.facts.flatMap((fact) => {
      const draft = drafts[fact.id]
      if (
        fact.origin !== "reported" ||
        !draft ||
        (draft.label === fact.label && draft.value_text === fact.value_text)
      ) {
        return []
      }
      return [{ id: fact.id, label: draft.label, value_text: draft.value_text }]
    })
  }, [drafts, review])

  const saveMutation = useMutation({
    mutationFn: (facts: ReviewFactUpdate[]) => saveDocumentReviewFacts(documentId, facts),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKey, data)
      setDrafts(initialDrafts(data.facts))
    },
  })
  const markMutation = useMutation({
    mutationFn: () => markDocumentReviewed(documentId),
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  })

  if (reviewQuery.isPending) {
    return (
      <main className="review-page">
        <div className="review-state"><LuLoaderCircle className="spin" /> Loading document review…</div>
      </main>
    )
  }
  if (reviewQuery.isError || !review) {
    return (
      <main className="review-page">
        <div className="review-topbar">
          <div className="review-breadcrumb"><Link href="/workspace/documents">Documents</Link><span>/</span><strong>Review</strong></div>
        </div>
        <div className="review-content">
          <div className="review-state is-error" role="alert">
            <LuTriangleAlert aria-hidden="true" />
            {reviewQuery.error?.message ?? "This document could not be loaded."}
          </div>
          <Link className="button button-outline" href="/workspace/documents"><LuArrowLeft /> Back to documents</Link>
        </div>
      </main>
    )
  }

  const selectedFact = review.facts.find((fact) => fact.id === selectedId) ?? review.facts[0] ?? null
  const selectedPage = manualPage ?? selectedFact?.locator.page ?? 1
  const validationFacts = review.facts.map((fact) => ({
    ...fact,
    label: drafts[fact.id]?.label ?? fact.label,
  }))
  const checks = validationChecks(validationFacts, drafts)
  const needsReviewCount = review.facts.filter((fact) => !fact.verified && fact.origin === "reported").length
  const isPdf = review.filename.toLowerCase().endsWith(".pdf")
  const periodText = shortPeriod(review.period_start, review.period_end)

  if (review.status !== "success") {
    return (
      <main className="review-page">
        <div className="review-topbar">
          <div className="review-breadcrumb"><Link href="/workspace/documents">Documents</Link><span>/</span><strong>Review</strong></div>
        </div>
        <div className="review-content">
          <div className="review-title-row"><div><h1>Review the facts. Keep the evidence.</h1><p>{review.filename}</p></div></div>
          <div className="review-state">
            <LuLoaderCircle className={review.status === "processing" ? "spin" : ""} aria-hidden="true" />
            {review.status === "processing" ? "This document is still processing. This page will refresh when it is ready." : `Document status: ${review.status}.`}
          </div>
        </div>
      </main>
    )
  }

  return (
    <main className="review-page">
      <div className="review-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace/documents">Documents</Link>
          <span aria-hidden="true">/</span>
          <strong>Review</strong>
        </div>
        <div className="review-topbar-meta">
          <span className="illustrative-tag">Source-backed extraction</span>
          <span>{new Date(review.upload_timestamp).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span>
        </div>
      </div>

      <div className="review-content">
        <div className="review-title-row">
          <div>
            <h1>Review the facts. Keep the evidence.</h1>
            <p>{review.filename}{review.organisation ? ` · ${review.organisation}` : ""}</p>
          </div>
          <div className="review-actions">
            <button
              className="button button-outline"
              type="button"
              disabled={dirtyFacts.length === 0 || saveMutation.isPending}
              onClick={() => saveMutation.mutate(dirtyFacts)}
            >
              {saveMutation.isPending ? <LuLoaderCircle className="spin" /> : <LuSave />}
              {saveMutation.isPending ? "Saving…" : "Save changes"}
            </button>
            <button
              className="button button-primary"
              type="button"
              disabled={dirtyFacts.length > 0 || markMutation.isPending || Boolean(review.reviewed_at)}
              onClick={() => markMutation.mutate()}
            >
              {markMutation.isPending ? <LuLoaderCircle className="spin" /> : <LuCheck />}
              {review.reviewed_at ? "Reviewed" : "Mark reviewed"}
            </button>
          </div>
        </div>

        <div className="review-status-row">
          <span className="review-status-pill is-ready">Ready</span>
          {needsReviewCount > 0 && <span className="review-status-pill is-review">{needsReviewCount} need review</span>}
          {review.reviewed_at && <span className="review-reviewed-note"><LuCheckCheck aria-hidden="true" /> Reviewed by {review.reviewed_by ?? "you"} · {dateTime(review.reviewed_at)}</span>}
          <span>{review.facts.length} fields extracted · {periodText} · {isPdf ? "PDF" : "Spreadsheet"}{review.page_count ? `, ${review.page_count} page${review.page_count === 1 ? "" : "s"}` : ""}</span>
        </div>

        {(saveMutation.isError || markMutation.isError) && (
          <div className="review-mutation-error" role="alert">
            {saveMutation.error?.message ?? markMutation.error?.message ?? "Unable to save review changes."}
          </div>
        )}

        <div className="review-grid">
          <div className="review-left-column">
            <section className="review-card review-facts-card" aria-label="Extracted fields">
              <div className="review-card-heading review-facts-heading">
                <div>
                  <h2>Extracted fields</h2>
                  <p>Source-reported values · Select a row to inspect its evidence.</p>
                </div>
                {dirtyFacts.length > 0 && <span className="review-unsaved">Unsaved edits</span>}
              </div>
              {review.facts.length === 0 ? (
                <div className="review-no-facts">No facts were saved for this document.</div>
              ) : (
                <div className="review-table-wrap">
                  <table className="review-table">
                    <thead><tr><th>Field</th><th>Extracted value</th><th>Source</th></tr></thead>
                    <tbody>
                      {review.facts.map((fact) => {
                        const draft = drafts[fact.id] ?? { label: fact.label, value_text: fact.value_text }
                        const selected = fact.id === selectedFact?.id
                        const changed = fact.edited || draft.label !== fact.label || draft.value_text !== fact.value_text
                        const valueNeedsCheck = !fact.verified || draft.value_text !== fact.value_text
                        return (
                          <tr
                            className={selected ? "is-selected" : ""}
                            key={fact.id}
                            onClick={() => {
                              setSelectedId(fact.id)
                              setManualPage(fact.locator.page)
                            }}
                          >
                            <td>
                              <input
                                className="review-input review-label-input"
                                aria-label={`Field name for ${fact.original_label}`}
                                value={draft.label}
                                disabled={fact.origin === "calculated"}
                                onFocus={() => setSelectedId(fact.id)}
                                onChange={(event) => setDrafts((current) => ({
                                  ...current,
                                  [fact.id]: { ...draft, label: event.target.value },
                                }))}
                              />
                              <div className="review-row-meta">
                                {fact.period_start && <span>{shortPeriod(fact.period_start, fact.period_end)}</span>}
                                {fact.origin === "calculated" && <span className="review-origin-tag">Calculated</span>}
                                {changed && fact.origin === "reported" && <span className="review-origin-tag is-edited">Edited</span>}
                                {!fact.verified && fact.origin === "reported" && !changed && <span className="review-origin-tag is-warning">Needs review</span>}
                              </div>
                            </td>
                            <td>
                              <input
                                className={`review-input review-value-input ${selected ? "is-emphasis" : ""}`}
                                aria-label={`Value for ${draft.label || fact.original_label}`}
                                value={draft.value_text}
                                disabled={fact.origin === "calculated"}
                                onFocus={() => setSelectedId(fact.id)}
                                onChange={(event) => setDrafts((current) => ({
                                  ...current,
                                  [fact.id]: { ...draft, value_text: event.target.value },
                                }))}
                              />
                              {fact.unit && <span className="review-unit-hint">{fact.unit}</span>}
                            </td>
                            <td>
                              <button
                                className={`review-source-link ${selected ? "is-selected" : ""}`}
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  setSelectedId(fact.id)
                                  setManualPage(fact.locator.page)
                                }}
                              >
                                {locatorText(fact)}
                              </button>
                              <span className={`review-source-dot ${!valueNeedsCheck ? "is-verified" : ""}`} aria-label={valueNeedsCheck ? "Source needs review" : "Source checked"} />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <ValidationCard checks={checks} issues={review.issues} />
            <RelatedSpreadsheetCard documents={relatedWorkbooks} />
          </div>

          <EvidencePanel
            review={review}
            fact={selectedFact}
            page={selectedPage}
            onPageChange={setManualPage}
          />
        </div>
      </div>
    </main>
  )
}
