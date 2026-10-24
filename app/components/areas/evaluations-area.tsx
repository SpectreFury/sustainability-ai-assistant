"use client"

import Link from "next/link"
import { useState } from "react"
import {
  LuArrowRight,
  LuCheck,
  LuDownload,
  LuFlaskConical,
  LuInfo,
  LuPlay,
  LuTriangleAlert,
  LuX,
} from "react-icons/lu"
import {
  allDimensionsPass,
  evaluationCases,
  evaluationDimensions,
  passedChecks,
  type EvaluationChecks,
} from "./evaluation-fixtures"

type EvaluationRun = "baseline" | "improved"

function checksFor(caseId: string, run: EvaluationRun): EvaluationChecks {
  const evaluationCase = evaluationCases.find((item) => item.id === caseId)
  return run === "baseline"
    ? evaluationCase?.baselineChecks ?? [false, false, false, false]
    : evaluationCase?.improvedChecks ?? [false, false, false, false]
}

function runLabel(run: EvaluationRun) {
  return run === "baseline" ? "Baseline · v0.1" : "Improved · v0.2"
}

function runAnswer(caseId: string, run: EvaluationRun) {
  const evaluationCase = evaluationCases.find((item) => item.id === caseId)
  return run === "baseline"
    ? evaluationCase?.baselineAnswer ?? ""
    : evaluationCase?.improvedAnswer ?? ""
}

function DimensionMarks({ checks }: { checks: EvaluationChecks }) {
  return (
    <span className="evaluation-marks" aria-label={`${passedChecks(checks)} of 4 dimensions pass`}>
      {checks.map((passed, index) => (
        <span
          aria-label={`${evaluationDimensions[index].label}: ${passed ? "pass" : "fail"}`}
          className={passed ? "is-pass" : "is-fail"}
          key={evaluationDimensions[index].key}
          title={`${evaluationDimensions[index].label}: ${passed ? "Pass" : "Fail"}`}
        >
          {passed ? <LuCheck aria-hidden="true" /> : <LuX aria-hidden="true" />}
        </span>
      ))}
    </span>
  )
}

function ResultBadge({ checks }: { checks: EvaluationChecks }) {
  const passed = allDimensionsPass(checks)
  return (
    <span className={`evaluation-result ${passed ? "is-pass" : "is-fail"}`}>
      {passed ? "Pass" : "Fail"}
    </span>
  )
}

function changeLabel(before: EvaluationChecks, after: EvaluationChecks) {
  const wasPassing = allDimensionsPass(before)
  const isPassing = allDimensionsPass(after)
  if (!wasPassing && isPassing) return { label: "Fixed", tone: "fixed" }
  if (wasPassing && !isPassing) return { label: "Regression", tone: "regression" }
  if (!wasPassing && !isPassing) return { label: "Unresolved", tone: "unresolved" }
  return { label: "Pass", tone: "pass" }
}

function scoresFor(run: EvaluationRun) {
  return evaluationDimensions.map((dimension, dimensionIndex) => ({
    ...dimension,
    passed: evaluationCases.filter((item) =>
      (run === "baseline" ? item.baselineChecks : item.improvedChecks)[dimensionIndex],
    ).length,
  }))
}

export function EvaluationsArea() {
  const [baselineRun, setBaselineRun] = useState<EvaluationRun>("baseline")
  const [improvedRun, setImprovedRun] = useState<EvaluationRun>("improved")
  const [runNotice, setRunNotice] = useState(false)
  const baselineScores = scoresFor(baselineRun)
  const improvedScores = scoresFor(improvedRun)
  const baselinePassed = evaluationCases.filter((item) =>
    allDimensionsPass(checksFor(item.id, baselineRun)),
  ).length
  const improvedPassed = evaluationCases.filter((item) =>
    allDimensionsPass(checksFor(item.id, improvedRun)),
  ).length
  const fixed = evaluationCases.filter(
    (item) =>
      !allDimensionsPass(checksFor(item.id, baselineRun)) &&
      allDimensionsPass(checksFor(item.id, improvedRun)),
  ).length
  const regressions = evaluationCases.filter(
    (item) =>
      allDimensionsPass(checksFor(item.id, baselineRun)) &&
      !allDimensionsPass(checksFor(item.id, improvedRun)),
  ).length
  const unresolved = evaluationCases.filter(
    (item) =>
      !allDimensionsPass(checksFor(item.id, baselineRun)) &&
      !allDimensionsPass(checksFor(item.id, improvedRun)),
  ).length
  const baselineChecks = baselineScores.reduce((total, item) => total + item.passed, 0)
  const improvedChecks = improvedScores.reduce((total, item) => total + item.passed, 0)

  function exportComparison() {
    const rows = [
      ["Case", "Question", `${runLabel(baselineRun)} result`, `${runLabel(improvedRun)} result`, "Change"],
      ...evaluationCases.map((item) => {
        const before = checksFor(item.id, baselineRun)
        const after = checksFor(item.id, improvedRun)
        return [
          item.id,
          item.question,
          allDimensionsPass(before) ? "Pass" : "Fail",
          allDimensionsPass(after) ? "Pass" : "Fail",
          changeLabel(before, after).label,
        ]
      }),
    ]
    const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n")
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "illustrative-evaluation-comparison.csv"
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <main className="evaluations-page">
      <header className="review-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace">Workspace</Link>
          <span aria-hidden="true">/</span>
          <strong>Evaluations</strong>
        </div>
        <div className="review-topbar-meta">
          <span className="illustrative-tag">Illustrative data</span>
          <span>24 Oct 2026</span>
          <span className="help-mark" aria-label="Evaluation help">?</span>
        </div>
      </header>

      <div className="evaluations-content">
        <div className="evaluations-title-row">
          <div>
            <h1>Better answers. Measurable evidence.</h1>
            <p>Compare the same ten illustrative cases across baseline and improved runs.</p>
          </div>
          <button className="button button-primary" onClick={() => setRunNotice(true)} type="button">
            <LuPlay aria-hidden="true" />
            Run evaluation
          </button>
        </div>

        {runNotice && (
          <div className="evaluation-notice" role="status">
            <LuInfo aria-hidden="true" />
            <p>
              No live evaluation was run. This workspace has no verified case pack or scoring runner
              connected yet; the comparison below is illustrative.
            </p>
            <button aria-label="Dismiss notice" onClick={() => setRunNotice(false)} type="button">
              <LuX aria-hidden="true" />
            </button>
          </div>
        )}

        <div className="evaluation-run-row">
          <label className="evaluation-select-wrap">
            <span className="sr-only">Baseline evaluation run</span>
            <select value={baselineRun} onChange={(event) => setBaselineRun(event.target.value as EvaluationRun)}>
              <option value="baseline">Baseline · v0.1</option>
              <option value="improved">Improved · v0.2</option>
            </select>
          </label>
          <span className="evaluation-compared">compared with</span>
          <label className="evaluation-select-wrap">
            <span className="sr-only">Improved evaluation run</span>
            <select value={improvedRun} onChange={(event) => setImprovedRun(event.target.value as EvaluationRun)}>
              <option value="improved">Improved · v0.2</option>
              <option value="baseline">Baseline · v0.1</option>
            </select>
          </label>
          <span className="evaluation-run-meta">Same 10 cases · 24 Oct 2026</span>
          <span className="evaluation-expected-tag">Illustrative expected answers</span>
        </div>

        <section className="evaluation-score-grid" aria-label="Evaluation summary">
          <article className="evaluation-score-card">
            <span>{runLabel(baselineRun)} · All dimensions pass</span>
            <strong>{baselinePassed} / 10</strong>
            <p>{Math.round((baselinePassed / 10) * 100)}% case pass rate · {baselineChecks} / 40 checks</p>
          </article>
          <article className="evaluation-score-card is-highlight">
            <span>{runLabel(improvedRun)} · All dimensions pass</span>
            <strong>{improvedPassed} / 10</strong>
            <p>{Math.round((improvedPassed / 10) * 100)}% case pass rate · {improvedChecks} / 40 checks</p>
          </article>
          <article className="evaluation-score-card">
            <span>Net change</span>
            <strong>{improvedPassed - baselinePassed >= 0 ? "+" : ""}{improvedPassed - baselinePassed} cases</strong>
            <p>{fixed} fixed · {regressions} regression · {unresolved} unresolved</p>
          </article>
        </section>

        <section className="evaluation-panel evaluation-dimensions">
          <div className="evaluation-panel-heading">
            <div>
              <h2>Dimension checks</h2>
              <p>A case passes only when all four dimensions pass.</p>
            </div>
          </div>
          <div className="evaluation-dimension-grid">
            {baselineScores.map((dimension, index) => (
              <div className="evaluation-dimension" key={dimension.key}>
                <span>{dimension.label}</span>
                <strong>{dimension.passed} <span aria-hidden="true">→</span> {improvedScores[index].passed} / 10</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="evaluation-panel">
          <div className="evaluation-panel-heading evaluation-cases-heading">
            <div>
              <h2>Case results</h2>
              <p>A / E / C / U = Answer / Evidence / Calculation / Uncertainty · ✓ Pass · × Fail</p>
            </div>
            <button className="evaluation-export" onClick={exportComparison} type="button">
              Export comparison <LuDownload aria-hidden="true" />
            </button>
          </div>
          <div className="evaluation-table-scroll">
            <table className="evaluation-table">
              <thead>
                <tr>
                  <th>Case &amp; question</th>
                  <th>Evidence / context</th>
                  <th>{baselineRun === "baseline" ? "Baseline" : "Improved"}</th>
                  <th>{improvedRun === "improved" ? "Improved" : "Baseline"}</th>
                  <th>Base A/E/C/U</th>
                  <th>New A/E/C/U</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {evaluationCases.map((item) => {
                  const before = checksFor(item.id, baselineRun)
                  const after = checksFor(item.id, improvedRun)
                  const change = changeLabel(before, after)
                  return (
                    <tr key={item.id}>
                      <td>
                        <Link className="evaluation-case-link" href={`/workspace/evaluations/${item.id}`}>
                          <span>{item.id}</span>
                          <strong>{item.question}</strong>
                          <LuArrowRight aria-hidden="true" />
                        </Link>
                      </td>
                      <td className="evaluation-context">{item.context}</td>
                      <td><ResultBadge checks={before} /></td>
                      <td><ResultBadge checks={after} /></td>
                      <td><DimensionMarks checks={before} /></td>
                      <td><DimensionMarks checks={after} /></td>
                      <td><span className={`evaluation-change is-${change.tone}`}>{change.label}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        <div className="evaluation-callouts">
          <aside className="evaluation-callout is-good">
            <LuInfo aria-hidden="true" />
            <div>
              <strong>Targeted improvement: amount semantics</strong>
              <p>v0.2 separates total payable from current charges and explicitly adds arrears when required. E01 and E02 now pass all dimensions.</p>
            </div>
          </aside>
          <aside className="evaluation-callout is-warning">
            <LuTriangleAlert aria-hidden="true" />
            <div>
              <strong>Do not promote this run without review</strong>
              <p>E09 regresses on an unsupported deadline; E10 still blends organizations. Expected answers and references need verification against original files.</p>
            </div>
          </aside>
        </div>
        <footer className="evaluation-footer">
          <span>KuKi / Environmental intelligence</span>
          <span>Illustrative comparison · Values and evidence locations are not verified</span>
        </footer>
      </div>
    </main>
  )
}

export function EvaluationDetailArea({ caseId }: { caseId: string }) {
  const evaluationCase = evaluationCases.find((item) => item.id === caseId)
  if (!evaluationCase) {
    return (
      <main className="evaluations-page">
        <header className="review-topbar"><div className="review-breadcrumb"><Link href="/workspace">Workspace</Link><span>/</span><Link href="/workspace/evaluations">Evaluations</Link><span>/</span><strong>Not found</strong></div></header>
        <div className="evaluations-content"><section className="evaluation-panel evaluation-not-found"><h1>Evaluation case not found</h1><p>This illustrative case is not in the current set.</p><Link className="button button-outline" href="/workspace/evaluations">All 10 cases</Link></section></div>
      </main>
    )
  }

  const index = evaluationCases.findIndex((item) => item.id === caseId)
  const previous = evaluationCases[(index - 1 + evaluationCases.length) % evaluationCases.length]
  const next = evaluationCases[(index + 1) % evaluationCases.length]
  const before = evaluationCase.baselineChecks
  const after = evaluationCase.improvedChecks
  const change = changeLabel(before, after)

  return (
    <main className="evaluations-page">
      <header className="review-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace">Workspace</Link><span aria-hidden="true">/</span>
          <Link href="/workspace/evaluations">Evaluations</Link><span aria-hidden="true">/</span>
          <strong>{evaluationCase.id}</strong>
        </div>
        <div className="review-topbar-meta"><span className="illustrative-tag">Illustrative data</span><span>24 Oct 2026</span><span className="help-mark" aria-label="Evaluation help">?</span></div>
      </header>

      <div className="evaluations-content">
        <div className="evaluations-detail-title-row">
          <div>
            <h1>{evaluationCase.id} · {evaluationCase.title}</h1>
            <p>Baseline v0.1 → Improved v0.2 · Same question, scope and expected behavior</p>
          </div>
          <Link className="button button-outline" href="/workspace/evaluations">← &nbsp; All 10 cases</Link>
        </div>
        <div className="evaluation-detail-status-row">
          <span className={`evaluation-change is-${change.tone}`}>{change.label}</span>
          <ResultBadge checks={before} />
          <span className="evaluation-detail-arrow">→</span>
          <ResultBadge checks={after} />
          <span>{evaluationCase.domain}</span>
          <nav className="evaluation-case-nav" aria-label="Evaluation cases">
            <Link href={`/workspace/evaluations/${previous.id}`}>← Previous</Link>
            <Link href={`/workspace/evaluations/${next.id}`}>Next case <LuArrowRight aria-hidden="true" /></Link>
          </nav>
        </div>

        <section className="evaluation-detail-brief">
          <div>
            <span>Question</span>
            <h2>{evaluationCase.question}</h2>
            <p>{evaluationCase.context}</p>
          </div>
          <div>
            <span>Expected behavior · illustrative until verified</span>
            <p className="evaluation-expected-copy">{evaluationCase.expected}</p>
            <small>Do not treat these example values or references as verified source evidence.</small>
          </div>
        </section>

        <section className="evaluation-answer-grid" aria-label="Compared answers">
          <article className="evaluation-answer-card is-baseline">
            <div className="evaluation-answer-heading"><div><h2>Baseline answer</h2><p>v0.1 · {passedChecks(before)} / 4 checks pass</p></div><span className="evaluation-answer-label">Baseline</span></div>
            <span className="evaluation-answer-result">{allDimensionsPass(before) ? "All checks pass" : "Needs improvement"}</span>
            <blockquote>“{runAnswer(evaluationCase.id, "baseline")}”</blockquote>
            <div className="evaluation-explanation is-negative"><LuTriangleAlert aria-hidden="true" /><div><strong>{allDimensionsPass(before) ? "Why this passes" : "What needs attention"}</strong><p>{evaluationCase.baselineFailure}</p></div></div>
          </article>
          <article className="evaluation-answer-card is-improved">
            <div className="evaluation-answer-heading"><div><h2>Improved answer</h2><p>v0.2 · {passedChecks(after)} / 4 checks pass</p></div><span className="evaluation-answer-label">Improved</span></div>
            <span className="evaluation-answer-result">{allDimensionsPass(after) ? "All checks pass" : "Needs review"}</span>
            <blockquote>“{runAnswer(evaluationCase.id, "improved")}”</blockquote>
            <div className="evaluation-explanation is-positive"><LuInfo aria-hidden="true" /><div><strong>What changed</strong><p>{evaluationCase.improvement}</p></div></div>
          </article>
        </section>

        <section className="evaluation-panel evaluation-check-panel">
          <div className="evaluation-panel-heading"><div><h2>Per-dimension checks</h2><p>A correct citation alone does not make an answer correct.</p></div></div>
          <div className="evaluation-table-scroll">
            <table className="evaluation-table evaluation-detail-table">
              <thead><tr><th>Dimension</th><th>Expected check</th><th>Baseline</th><th>Improved</th></tr></thead>
              <tbody>
                {evaluationDimensions.map((dimension, dimensionIndex) => (
                  <tr key={dimension.key}>
                    <td>{dimension.label}</td>
                    <td>{dimensionIndex === 0 ? "Answer the question using only the requested scope and variant." : dimensionIndex === 1 ? "Cite the precise source location and supporting value." : dimensionIndex === 2 ? "Show only calculations that follow from the cited values." : "State missing, conflicting, or uncertain evidence without filling gaps."}</td>
                    <td><ResultBadge checks={[before[dimensionIndex], true, true, true]} /></td>
                    <td><ResultBadge checks={[after[dimensionIndex], true, true, true]} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="evaluation-detail-bottom-grid">
          <section className="evaluation-panel evaluation-evidence-panel">
            <div className="evaluation-panel-heading"><div><h2>Expected evidence</h2><p>Example reference · not a verified original excerpt</p></div></div>
            <Link className="evaluation-source-link" href="/workspace/documents">{evaluationCase.context} ↗</Link>
            <div className="evaluation-evidence-values">
              {evaluationCase.evidence.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}
            </div>
          </section>
          <aside className="evaluation-panel evaluation-limitations">
            <h2>Remaining limitations</h2>
            <p>{evaluationCase.limitations}</p>
            <p>Verify the original file, expected answer, and evidence locations before treating this comparison as a ground truth.</p>
          </aside>
        </div>
        <footer className="evaluation-footer"><span>KuKi / Environmental intelligence</span><span>Illustrative comparison · Values and evidence locations are not verified</span></footer>
      </div>
    </main>
  )
}
