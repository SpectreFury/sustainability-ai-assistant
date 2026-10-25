import { EvaluationDetailArea } from "@/components/areas/evaluations-area"
import { Suspense } from "react"

async function EvaluationCaseContent({
  params,
}: {
  params: Promise<{ caseId: string }>
}) {
  const { caseId } = await params
  return <EvaluationDetailArea caseId={caseId} />
}

function EvaluationCaseFallback() {
  return (
    <main className="evaluations-page" aria-busy="true">
      <div className="evaluations-content">
        <p role="status">Loading evaluation case…</p>
      </div>
    </main>
  )
}

export default function EvaluationCasePage({
  params,
}: {
  params: Promise<{ caseId: string }>
}) {
  return (
    <Suspense fallback={<EvaluationCaseFallback />}>
      <EvaluationCaseContent params={params} />
    </Suspense>
  )
}
