export type AnswerStatus =
  | "answered"
  | "partial"
  | "insufficient_evidence"
  | "conflicting_evidence"

export type AnswerLocator = {
  page?: number | null
  sheet?: string | null
  cell_range?: string | null
}

export type AnswerEvidence = {
  id: string
  document_id: string
  filename: string
  locator: AnswerLocator
  locator_label: string
  quote: string
  source_preview: string
  verified: boolean
  verification: string
}

export type AnswerKeyValue = {
  label: string
  value: string | null
  value_text: string
  unit: string | null
  period: string | null
  origin: "reported" | "calculated"
  evidence_ids: string[]
  calculation_id: string | null
  verified: boolean
  verification: string
}

export type AnswerCalculation = {
  id: string
  description: string
  expression: string
  result: string
  computed: string | null
  matches: boolean
  unit: string | null
  evidence_ids: string[]
  verification: string
}

export type AnswerContent = {
  answer: string
  key_values: AnswerKeyValue[]
  calculations: AnswerCalculation[]
  evidence: AnswerEvidence[]
  gaps: string[]
  model: string
}

export type AnswerRecord = {
  id: string
  question: string
  document_ids: string[]
  status: AnswerStatus
  answer: AnswerContent
  created_at: string
}

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL

async function parseError(response: Response, fallback: string): Promise<Error> {
  const result = await response.json().catch(() => null)
  return new Error(
    typeof result?.detail === "string" ? result.detail : fallback,
  )
}

export async function askQuestion(
  question: string,
  documentIds: string[],
): Promise<AnswerRecord> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

  const response = await fetch(`${backendUrl}/answers`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, document_ids: documentIds }),
  })
  if (!response.ok) {
    throw await parseError(response, "Unable to answer this question.")
  }
  return response.json()
}

export async function getAnswerHistory(limit = 20): Promise<AnswerRecord[]> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

  const response = await fetch(`${backendUrl}/answers?limit=${limit}`, {
    credentials: "include",
    cache: "no-store",
  })
  if (!response.ok) {
    throw await parseError(response, "Unable to load answer history.")
  }
  return response.json()
}
