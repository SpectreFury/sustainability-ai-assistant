"use client"

import { EvaluationDetailArea } from "@/components/areas/evaluations-area"
import { useParams } from "next/navigation"

export default function EvaluationCasePage() {
  const params = useParams<{ caseId: string }>()
  return <EvaluationDetailArea caseId={params.caseId} />
}
