export type EvaluationStatus = "queued" | "running" | "completed" | "failed"
export type EvaluationDimension = "answer" | "extraction" | "evidence" | "calculation" | "uncertainty"

export type EvaluationCheckSet = Record<EvaluationDimension, boolean | null>
export type EvaluationCheckDetails = Partial<Record<EvaluationDimension, string[]>>

export type EvaluationEvidenceExpectation = {
  filename: string
  page?: number
  sheet?: string
  cell?: string
  quote_terms?: string[]
}

export type EvaluationCase = {
  id: string
  title: string
  question: string
  domain: string
  runner: "answer" | "financial_year_summary"
  required_documents: string[]
  expected_status: string
  expected_evidence: EvaluationEvidenceExpectation[]
}

export type EvaluationAnswer = {
  status: string
  answer: string
  key_values: Array<{
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
  }>
  calculations: Array<{
    id: string
    description: string
    expression: string
    result: string
    computed: string | null
    matches: boolean
    unit: string | null
    evidence_ids: string[]
    verification: string
  }>
  evidence: Array<{
    id: string
    document_id: string
    filename: string
    locator: { page?: number | null; sheet?: string | null; cell_range?: string | null }
    locator_label: string
    quote: string
    source_preview: string
    verified: boolean
    verification: string
  }>
  gaps: string[]
  model: string
}

export type EvaluationCaseResult = {
  case_id: string
  case: EvaluationCase
  status: "evaluated" | "blocked" | "error"
  passed: boolean | null
  checks: EvaluationCheckSet
  check_details?: EvaluationCheckDetails
  expected_status?: string
  actual_status?: string
  answer: EvaluationAnswer | null
  financial_year_summary?: {
    financial_year: string
    financial_year_start: string
    financial_year_end: string
    organisation: string | null
    coverage_status: string
    metrics: Array<{
      metric: string
      label: string
      series: string | null
      unit: string | null
      value: string | null
      status: string
      period_label: string
      method: string
      calculation: string | null
      months_covered: number
      months: Array<{ label: string; covered: boolean; value: string | null }>
      note: string | null
    }>
    sources: Array<{
      filename: string
      label: string
      metric: string | null
      series: string | null
      unit: string | null
      value: string
      value_text: string
      period_start: string | null
      period_end: string | null
      locator: { page?: number | null; sheet?: string | null; cell_range?: string | null }
      quote: string | null
      verified: boolean
      treatment: string
      reason: string
    }>
    gaps: string[]
  } | null
  metric_label?: string | null
  metric_value?: string | null
  metric_unit?: string | null
  period_label?: string | null
  months_covered?: number
  error_message: string | null
  failure_stage?: string | null
  failure_type?: string | null
  failure_attempts?: number | null
  failure_diagnostic?: string | null
  retryable?: boolean | null
  answer_attempts?: number | null
  document_snapshot: Record<string, { document_id: string | null; file_hash: string | null; status_at_start: string | null; extraction_model?: string | null; extraction_pipeline?: string | null; extraction_prompt_hash?: string | null; extraction_attempts?: number | null; financial_year_extraction_run_id?: string | null }>
  duration_ms: number | null
}

export type EvaluationRunSummary = {
  id: string
  status: EvaluationStatus
  current_stage: string | null
  case_set_version: string
  model_name: string | null
  case_count: number
  completed_count: number
  passed_count: number
  evaluated_count: number
  blocked_count: number
  error_count: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  error_message: string | null
}

export type EvaluationRun = EvaluationRunSummary & {
  case_set_hash: string
  answer_prompt_hash: string
  extraction_prompt_hash: string
  document_snapshot: Record<string, { document_id: string | null; file_hash: string | null; status_at_start: string | null; extraction_model?: string | null; extraction_pipeline?: string | null; extraction_prompt_hash?: string | null; extraction_attempts?: number | null; financial_year_extraction_run_id?: string | null }>
  case_results: EvaluationCaseResult[]
}

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL

async function parseError(response: Response, fallback: string): Promise<Error> {
  const result = await response.json().catch(() => null)
  return new Error(typeof result?.detail === "string" ? result.detail : fallback)
}

async function getJson<T>(path: string): Promise<T> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  const response = await fetch(`${backendUrl}${path}`, {
    credentials: "include",
    cache: "no-store",
  })
  if (!response.ok) throw await parseError(response, "Unable to load evaluations.")
  return response.json()
}

export function getEvaluationCases(): Promise<EvaluationCase[]> {
  return getJson<EvaluationCase[]>("/evaluations/cases")
}

export function getEvaluationRuns(limit = 10): Promise<EvaluationRunSummary[]> {
  return getJson<EvaluationRunSummary[]>(`/evaluations/runs?limit=${limit}`)
}

export function getEvaluationRun(runId: string): Promise<EvaluationRun> {
  return getJson<EvaluationRun>(`/evaluations/runs/${runId}`)
}

export async function startEvaluationRun(): Promise<{
  id: string
  status: EvaluationStatus
  current_stage: string | null
  case_set_version: string
  case_count: number
  created_at: string
}> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  const response = await fetch(`${backendUrl}/evaluations/runs`, {
    method: "POST",
    credentials: "include",
  })
  if (!response.ok) throw await parseError(response, "Unable to start an evaluation.")
  return response.json()
}
