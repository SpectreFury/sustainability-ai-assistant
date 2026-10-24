"use client"

import {
  askQuestion,
  getAnswerHistory,
  type AnswerEvidence,
  type AnswerRecord,
  type AnswerStatus,
} from "@/api/answers"
import { getDocuments, type DocumentRecord } from "@/api/documents"
import {
  LuArrowRight,
  LuArrowUp,
  LuCheck,
  LuChevronDown,
  LuCircleCheck,
  LuClock3,
  LuCopy,
  LuExternalLink,
  LuFileText,
  LuFiles,
  LuHistory,
  LuLoaderCircle,
  LuPlus,
  LuSparkles,
  LuTriangleAlert,
  LuUpload,
  LuX,
} from "react-icons/lu"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState, type FormEvent, type ReactNode } from "react"

type AskAreaProps = {
  onNavigateUpload: () => void
}

type AskTurn = {
  key: string
  question: string
  documentIds: string[]
  record: AnswerRecord | null
  error: string | null
}

type ActiveSource = {
  recordId: string
  evidence: AnswerEvidence
}

const STATUS_LABEL: Record<AnswerStatus, string> = {
  answered: "Answered",
  partial: "Partially supported",
  insufficient_evidence: "Not established",
  conflicting_evidence: "Conflicting evidence",
}

function createTurnKey() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function filenameLabel(filename: string) {
  return filename.replace(/\.(pdf|xlsx)$/i, "")
}

function locatorLabel(evidence: AnswerEvidence) {
  if (evidence.locator.page != null) return `Page ${evidence.locator.page}`
  if (evidence.locator.sheet) {
    return `${evidence.locator.sheet}${evidence.locator.cell_range ? ` · ${evidence.locator.cell_range}` : ""}`
  }
  return evidence.locator_label
}

function dateLabel(value: string) {
  return new Date(value).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function inlineCitations(
  text: string,
  evidence: AnswerEvidence[],
  onSelect: (item: AnswerEvidence) => void,
): ReactNode[] {
  return text.split(/(\[E\d+\])/g).map((part, index) => {
    const match = /^\[(E\d+)\]$/.exec(part)
    const item = match ? evidence.find((source) => source.id === match[1]) : null
    if (!match || !item) return <span key={index}>{part}</span>
    return (
      <button
        key={index}
        type="button"
        className="answer-citation"
        aria-label={`Open source ${match[1].slice(1)}`}
        onClick={() => onSelect(item)}
      >
        [{match[1].slice(1)}]
      </button>
    )
  })
}

function AnswerNarrative({
  text,
  evidence,
  onSelect,
}: {
  text: string
  evidence: AnswerEvidence[]
  onSelect: (item: AnswerEvidence) => void
}) {
  const paragraphs = text.split(/\n\s*\n/).filter(Boolean)
  return (
    <div className="answer-narrative">
      {paragraphs.map((paragraph, index) => (
        <p className={index === 0 ? "answer-lede" : "answer-copy"} key={index}>
          {paragraph.split("\n").map((line, lineIndex) => (
            <span key={lineIndex}>
              {lineIndex > 0 && <br />}
              {inlineCitations(line, evidence, onSelect)}
            </span>
          ))}
        </p>
      ))}
    </div>
  )
}

function AnswerCard({
  turn,
  busy,
  onSourceSelect,
  onRetry,
  copied,
  onCopy,
}: {
  turn: AskTurn
  busy: boolean
  onSourceSelect: (record: AnswerRecord, evidence: AnswerEvidence) => void
  onRetry: (turn: AskTurn) => void
  copied: boolean
  onCopy: (record: AnswerRecord) => void
}) {
  const record = turn.record
  if (!record) {
    if (turn.error) {
      return (
        <div className="answer-error" role="alert">
          <LuTriangleAlert aria-hidden="true" />
          <div>
            <strong>KuKi couldn&apos;t finish this answer.</strong>
            <p>{turn.error}</p>
          </div>
          <button
            className="button button-small"
            type="button"
            disabled={busy}
            onClick={() => onRetry(turn)}
          >
            Try again
          </button>
        </div>
      )
    }
    return (
      <div className="answer-thinking" role="status" aria-live="polite">
        <LuLoaderCircle className="spin" aria-hidden="true" />
        <span>Checking the selected documents and their source locations…</span>
      </div>
    )
  }

  const answer = record.answer
  const allSourcesVerified =
    answer.evidence.length > 0 && answer.evidence.every((item) => item.verified)
  const allCalculationsMatch =
    answer.calculations.length > 0 && answer.calculations.every((item) => item.matches)

  return (
    <article className="answer-card" aria-label="Answer">
      <div className="answer-card-heading">
        <div className="answer-byline">
          <span className="answer-mark">
            <LuSparkles aria-hidden="true" />
          </span>
          <strong>KuKi</strong>
          <span className={`status-pill status-${record.status}`}>
            {STATUS_LABEL[record.status]}
          </span>
        </div>
        <span className="answer-meta">
          {answer.evidence.length} source{answer.evidence.length === 1 ? "" : "s"}
          {allSourcesVerified && " · source locations checked"}
          {allCalculationsMatch && " · calculations rechecked"}
        </span>
      </div>

      <AnswerNarrative
        text={answer.answer}
        evidence={answer.evidence}
        onSelect={(item) => onSourceSelect(record, item)}
      />

      {answer.key_values.length > 0 && (
        <section className="answer-key-figures" aria-label="Key figures">
          <h3>Key figures</h3>
          <div className="key-figure-list">
            {answer.key_values.map((value, index) => (
              <div className="key-figure" key={`${value.label}-${index}`}>
                <div>
                  <strong>{value.label}</strong>
                  {value.period && <span>{value.period}</span>}
                </div>
                <strong className="key-figure-value">{value.value_text}</strong>
                <span
                  className={`origin-tag origin-${value.origin} ${value.verified ? "" : "origin-unverified"}`}
                  title={value.verification}
                >
                  {value.origin}{value.verified ? " · checked" : " · unconfirmed"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {answer.calculations.length > 0 && (
        <section className="calculation-list" aria-label="How it was calculated">
          <div className="section-heading-row">
            <h3>How it was calculated</h3>
            <span>Re-run by the server</span>
          </div>
          {answer.calculations.map((calculation) => (
            <div className="calculation-item" key={calculation.id}>
              <p>{calculation.description}</p>
              <div className="calculation-expression">
                <code>
                  {calculation.expression} = {calculation.result}
                  {calculation.unit ? ` ${calculation.unit}` : ""}
                </code>
                <span className={calculation.matches ? "verdict-good" : "verdict-warn"}>
                  {calculation.matches ? (
                    <>
                      <LuCircleCheck aria-hidden="true" /> Checked
                    </>
                  ) : (
                    <>
                      <LuTriangleAlert aria-hidden="true" /> Check this step
                    </>
                  )}
                </span>
              </div>
              {calculation.computed !== null && !calculation.matches && (
                <p className="calculation-note">
                  Server recomputed {calculation.computed}. {calculation.verification}
                </p>
              )}
            </div>
          ))}
        </section>
      )}

      {answer.gaps.length > 0 && (
        <section className="answer-gaps" aria-label="What this answer cannot establish">
          <div className="gaps-title">
            <LuTriangleAlert aria-hidden="true" />
            <strong>What this answer cannot establish</strong>
          </div>
          <ul>
            {answer.gaps.map((gap, index) => <li key={`${gap}-${index}`}>{gap}</li>)}
          </ul>
        </section>
      )}

      {answer.evidence.length > 0 && (
        <section className="answer-evidence-list" aria-label="Evidence">
          <h3>Evidence</h3>
          {answer.evidence.map((item) => (
            <button
              className="evidence-link"
              type="button"
              key={item.id}
              onClick={() => onSourceSelect(record, item)}
            >
              <span className="evidence-link-text">
                <span className="evidence-number">[{item.id.slice(1)}]</span>
                <span>{item.filename} · {locatorLabel(item)}</span>
                <span className="evidence-quote">“{item.quote}”</span>
              </span>
              <span className={item.verified ? "evidence-found" : "evidence-unconfirmed"}>
                {item.verified ? "Found" : "Not confirmed"}
              </span>
            </button>
          ))}
        </section>
      )}

      <div className="answer-card-footer">
        <button className="text-action" type="button" onClick={() => onCopy(record)}>
          {copied ? <LuCheck aria-hidden="true" /> : <LuCopy aria-hidden="true" />}
          {copied ? "Copied" : "Copy answer"}
        </button>
        <span>{record.document_ids.length} document{record.document_ids.length === 1 ? "" : "s"} searched</span>
      </div>
    </article>
  )
}

function SourcePanel({
  source,
  documents,
}: {
  source: ActiveSource | null
  documents: DocumentRecord[]
}) {
  if (!source) {
    return (
      <section className="side-card source-panel" aria-label="Source evidence">
        <h2>Source evidence</h2>
        <p className="side-card-lede">Cited pages and cells will appear here with each answer.</p>
        <div className="source-empty">
          <LuFiles aria-hidden="true" />
          <span>Ask a question to inspect its sources.</span>
        </div>
      </section>
    )
  }

  const evidence = source.evidence
  const document = documents.find((item) => item.id === evidence.document_id)
  return (
    <section className="side-card source-panel" aria-label={`Source ${evidence.id}`}>
      <div className="source-panel-heading">
        <div>
          <h2>Source [{evidence.id.slice(1)}]</h2>
          <p>{filenameLabel(evidence.filename)} · {locatorLabel(evidence)}</p>
        </div>
        <span className={evidence.verified ? "source-state is-verified" : "source-state is-unverified"}>
          {evidence.verified ? "CHECKED" : "REVIEW"}
        </span>
      </div>

      <div className="source-document-preview">
        <div className="source-preview-topline">
          <strong>{filenameLabel(evidence.filename)}</strong>
          <span>{evidence.verified ? "SOURCE LOCATION" : "UNCONFIRMED"}</span>
        </div>
        <blockquote>{evidence.quote}</blockquote>
        <div className="source-preview-context">
          <span>Source context</span>
          <pre>{evidence.source_preview || "No text preview is available for this location."}</pre>
        </div>
        <p className={`source-verification ${evidence.verified ? "" : "is-warning"}`}>
          {evidence.verified ? <LuCheck aria-hidden="true" /> : <LuTriangleAlert aria-hidden="true" />}
          {evidence.verification}
        </p>
      </div>

      {document?.cloudinary_url && (
        <a
          className="source-open-link"
          href={document.cloudinary_url}
          target="_blank"
          rel="noreferrer"
        >
          Open original document <LuExternalLink aria-hidden="true" />
        </a>
      )}
    </section>
  )
}

export function AskArea({ onNavigateUpload }: AskAreaProps) {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState("")
  const [turns, setTurns] = useState<AskTurn[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string> | null>(null)
  const [scopeOpen, setScopeOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null)
  const [copiedRecordId, setCopiedRecordId] = useState<string | null>(null)

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: getDocuments,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === "processing")
        ? 3000
        : false,
  })
  const historyQuery = useQuery({
    queryKey: ["answer-history"],
    queryFn: () => getAnswerHistory(30),
    enabled: historyOpen,
    retry: false,
  })

  const allDocuments = documentsQuery.data ?? []
  const readyDocuments = allDocuments.filter((document) => document.status === "success")
  const pendingDocuments = allDocuments.filter(
    (document) => document.status === "pending" || document.status === "processing",
  ).length
  const selectedDocuments = selectedIds === null
    ? readyDocuments
    : readyDocuments.filter((document) => selectedIds.has(document.id))
  const selectedDocumentIds = selectedDocuments.map((document) => document.id)
  const busy = pendingKey !== null

  const setTurn = (key: string, update: Partial<AskTurn>) => {
    setTurns((current) =>
      current.map((turn) => turn.key === key ? { ...turn, ...update } : turn),
    )
  }

  const runAnswer = async (key: string, text: string, documentIds: string[]) => {
    setPendingKey(key)
    setTurn(key, { error: null, record: null })
    setActiveSource(null)
    try {
      const record = await askQuestion(text, documentIds)
      setTurn(key, { record })
      const firstEvidence = record.answer.evidence[0]
      if (firstEvidence) {
        setActiveSource({ recordId: record.id, evidence: firstEvidence })
      }
      void queryClient.invalidateQueries({ queryKey: ["answer-history"] })
    } catch (error) {
      setTurn(key, {
        error: error instanceof Error ? error.message : "Please try again in a moment.",
      })
    } finally {
      setPendingKey(null)
    }
  }

  const submitQuestion = async (event?: FormEvent<HTMLFormElement>, text = question) => {
    event?.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || busy || selectedDocumentIds.length === 0) return

    const key = createTurnKey()
    const turn: AskTurn = {
      key,
      question: trimmed,
      documentIds: selectedDocumentIds,
      record: null,
      error: null,
    }
    setQuestion("")
    setTurns((current) => [...current, turn])
    await runAnswer(key, trimmed, selectedDocumentIds)
  }

  const retryTurn = (turn: AskTurn) => {
    void runAnswer(turn.key, turn.question, turn.documentIds)
  }

  const toggleDocument = (documentId: string) => {
    const next = new Set(selectedIds ?? readyDocuments.map((document) => document.id))
    if (next.has(documentId)) next.delete(documentId)
    else next.add(documentId)
    setSelectedIds(next)
  }

  const chooseHistory = (record: AnswerRecord) => {
    setTurns([{
      key: record.id,
      question: record.question,
      documentIds: record.document_ids,
      record,
      error: null,
    }])
    setSelectedIds(new Set(record.document_ids.filter((id) => readyDocuments.some((document) => document.id === id))))
    const firstEvidence = record.answer.evidence[0]
    setActiveSource(firstEvidence ? { recordId: record.id, evidence: firstEvidence } : null)
    setHistoryOpen(false)
  }

  const startNewConversation = () => {
    setTurns([])
    setQuestion("")
    setActiveSource(null)
    setCopiedRecordId(null)
  }

  const copyAnswer = async (record: AnswerRecord) => {
    try {
      await navigator.clipboard.writeText(record.answer.answer)
      setCopiedRecordId(record.id)
    } catch {
      setCopiedRecordId(null)
    }
  }

  const selectSource = (record: AnswerRecord, evidence: AnswerEvidence) => {
    setActiveSource({ recordId: record.id, evidence })
  }

  return (
    <div className="ask-page">
      <header className="ask-topbar">
        <div className="ask-breadcrumb">
          <span>Workspace</span>
          <span aria-hidden="true">/</span>
          <strong>Ask AI</strong>
        </div>
        <div className="ask-topbar-right">
          <span className="topbar-evidence-badge"><LuCircleCheck aria-hidden="true" /> Citation checks enabled</span>
          <span className="topbar-document-count">
            {readyDocuments.length} ready document{readyDocuments.length === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      <main className="ask-content">
        <div className="ask-title-row">
          <div>
            <h1>Ask a question. See the evidence.</h1>
            <p>Answers use only the documents you choose, with calculations you can inspect.</p>
          </div>
          <button className="button button-outline new-conversation" type="button" onClick={startNewConversation}>
            <LuPlus aria-hidden="true" /> New conversation
          </button>
        </div>

        <section className="document-scope" aria-label="Document scope">
          <div className="scope-summary">
            <span className="scope-icon"><LuFiles aria-hidden="true" /></span>
            <strong>Document scope</strong>
            <span className="scope-count">
              {selectedDocuments.length} selected · {readyDocuments.length} ready
            </span>
            <span className="scope-note">
              {selectedDocuments.length > 0 ? "Answers are limited to this selection" : "Choose at least one ready document"}
            </span>
            <button className="button button-outline scope-change" type="button" onClick={() => setScopeOpen(true)}>
              Change scope <LuChevronDown aria-hidden="true" />
            </button>
          </div>
          <div className="scope-chips">
            {documentsQuery.isPending && <span className="scope-loading">Loading documents…</span>}
            {documentsQuery.isError && (
              <span className="scope-error" role="alert">{documentsQuery.error.message}</span>
            )}
            {selectedDocuments.map((document) => (
              <span className="scope-chip" key={document.id} title={document.filename}>
                <LuCheck aria-hidden="true" /> {document.filename}
              </span>
            ))}
            {!documentsQuery.isPending && !documentsQuery.isError && selectedDocuments.length === 0 && (
              <button className="text-action scope-upload-link" type="button" onClick={onNavigateUpload}>
                Upload a document <LuArrowRight aria-hidden="true" />
              </button>
            )}
          </div>
        </section>

        <div className="ask-columns">
          <section className="conversation-column" aria-label="Question and answer thread">
            <div className="conversation-toolbar">
              <span><LuClock3 aria-hidden="true" /> {turns.length > 0 ? "This conversation" : "Ready when you are"}</span>
              <button type="button" className="text-action history-trigger" onClick={() => setHistoryOpen(true)}>
                <LuHistory aria-hidden="true" /> View history <span aria-hidden="true">↗</span>
              </button>
            </div>

            {turns.length === 0 ? (
              <div className="ask-empty-state">
                <span className="empty-sparkle"><LuSparkles aria-hidden="true" /></span>
                {selectedDocuments.length > 0 ? (
                  <>
                    <h2>Your documents are in scope.</h2>
                    <p>Ask about a number, a period, or a discrepancy. KuKi will show the supporting source locations.</p>
                  </>
                ) : (
                  <>
                    <h2>No processed documents in scope yet.</h2>
                    <p>Upload and process a PDF or workbook, then come back to ask about its evidence.</p>
                    <button className="button button-primary" type="button" onClick={onNavigateUpload}>
                      <LuUpload aria-hidden="true" /> Go to upload
                    </button>
                  </>
                )}
                {documentsQuery.isError && <p className="inline-error" role="alert">{documentsQuery.error.message}</p>}
              </div>
            ) : (
              <div className="conversation-thread">
                {turns.map((turn) => (
                  <div className="conversation-turn" key={turn.key}>
                    <div className="user-question">
                      <span className="question-label">YOU</span>
                      <p>{turn.question}</p>
                      <span className="question-scope">{turn.documentIds.length} source document{turn.documentIds.length === 1 ? "" : "s"}</span>
                    </div>
                    <AnswerCard
                      turn={turn}
                      busy={pendingKey === turn.key}
                      onSourceSelect={selectSource}
                      onRetry={retryTurn}
                      copied={copiedRecordId === turn.record?.id}
                      onCopy={(record) => void copyAnswer(record)}
                    />
                  </div>
                ))}
              </div>
            )}

            <form className="ask-composer" onSubmit={(event) => void submitQuestion(event)}>
              <label className="visually-hidden" htmlFor="ask-question">Ask a question about the selected documents</label>
              <textarea
                id="ask-question"
                rows={1}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    void submitQuestion()
                  }
                }}
                placeholder={turns.length > 0 ? `Ask a follow-up about these ${selectedDocuments.length} documents…` : "Ask a question about your documents…"}
                disabled={busy || selectedDocuments.length === 0}
              />
              <button
                className="button button-primary send-button"
                type="submit"
                disabled={busy || !question.trim() || selectedDocuments.length === 0}
                aria-label={busy ? "Checking documents" : "Send question"}
              >
                {busy ? <LuLoaderCircle className="spin" aria-hidden="true" /> : <LuArrowUp aria-hidden="true" />}
                <span>{busy ? "Checking" : "Send"}</span>
              </button>
            </form>
            <p className="composer-hint">
              Looking in {selectedDocuments.length} of {readyDocuments.length} processed document{readyDocuments.length === 1 ? "" : "s"}
              {pendingDocuments > 0 ? ` · ${pendingDocuments} still processing` : ""}
              {turns.length > 0 ? " · each question is checked against its sources" : ""}
            </p>
          </section>

          <aside className="ask-aside">
            <SourcePanel source={activeSource} documents={allDocuments} />
          </aside>
        </div>

        <footer className="ask-footer">
          <span>KuKi / Environmental intelligence</span>
          <span>Answers are limited to your selected documents and checked against stored source locations.</span>
        </footer>
      </main>

      {scopeOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setScopeOpen(false)
        }}>
          <section className="ask-modal" role="dialog" aria-modal="true" aria-labelledby="scope-dialog-title">
            <div className="modal-heading">
              <div>
                <span className="modal-eyebrow">SEARCH SCOPE</span>
                <h2 id="scope-dialog-title">Choose documents</h2>
                <p>Only successfully processed documents can be searched.</p>
              </div>
              <button className="icon-button modal-close" type="button" aria-label="Close document scope" onClick={() => setScopeOpen(false)}>
                <LuX aria-hidden="true" />
              </button>
            </div>
            <div className="scope-options">
              {allDocuments.length === 0 && !documentsQuery.isPending && (
                <p className="history-empty">No documents have been uploaded yet.</p>
              )}
              {allDocuments.map((document) => {
                const ready = document.status === "success"
                const checked = ready && (selectedIds === null || selectedIds.has(document.id))
                return (
                  <label className={`scope-option ${!ready ? "is-disabled" : ""}`} key={document.id}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!ready}
                      onChange={() => toggleDocument(document.id)}
                    />
                    <span className="scope-option-icon"><LuFileText aria-hidden="true" /></span>
                    <span className="scope-option-details">
                      <strong>{document.filename}</strong>
                      <span>{document.status === "success" ? "Ready to search" : document.error_message ?? document.status}</span>
                    </span>
                    <span className={`document-status-dot status-dot-${document.status}`} />
                  </label>
                )
              })}
            </div>
            <div className="modal-actions">
              <button className="text-action" type="button" onClick={() => setSelectedIds(new Set())}>Clear selection</button>
              <button className="button button-primary" type="button" onClick={() => setScopeOpen(false)}>
                Use {selectedDocuments.length} document{selectedDocuments.length === 1 ? "" : "s"}
              </button>
            </div>
          </section>
        </div>
      )}

      {historyOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setHistoryOpen(false)
        }}>
          <section className="ask-modal history-modal" role="dialog" aria-modal="true" aria-labelledby="history-dialog-title">
            <div className="modal-heading">
              <div>
                <span className="modal-eyebrow">SAVED ANSWERS</span>
                <h2 id="history-dialog-title">Question history</h2>
                <p>Open an earlier answer with its original citations and document scope.</p>
              </div>
              <button className="icon-button modal-close" type="button" aria-label="Close question history" onClick={() => setHistoryOpen(false)}>
                <LuX aria-hidden="true" />
              </button>
            </div>
            {historyQuery.isPending ? (
              <div className="history-loading"><LuLoaderCircle className="spin" aria-hidden="true" /> Loading saved answers…</div>
            ) : historyQuery.isError ? (
              <p className="inline-error" role="alert">{historyQuery.error.message}</p>
            ) : historyQuery.data?.length ? (
              <div className="history-list">
                {historyQuery.data.map((record) => (
                  <button className="history-item" type="button" key={record.id} onClick={() => chooseHistory(record)}>
                    <span className={`history-status status-${record.status}`} />
                    <span className="history-item-copy">
                      <strong>{record.question}</strong>
                      <span>{dateLabel(record.created_at)} · {record.document_ids.length} document{record.document_ids.length === 1 ? "" : "s"}</span>
                    </span>
                    <LuArrowRight aria-hidden="true" />
                  </button>
                ))}
              </div>
            ) : (
              <div className="history-empty">
                <LuHistory aria-hidden="true" />
                <strong>No saved answers yet</strong>
                <span>Your questions and cited responses will appear here.</span>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
