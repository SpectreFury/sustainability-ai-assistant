"use client"

import { DocumentReviewArea } from "@/components/areas/document-review-area"
import { useParams } from "next/navigation"

export default function DocumentReviewPage() {
  const params = useParams<{ documentId: string }>()
  return <DocumentReviewArea documentId={params.documentId} />
}
