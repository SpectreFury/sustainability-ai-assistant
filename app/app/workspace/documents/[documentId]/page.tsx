import { DocumentReviewArea } from "@/components/areas/document-review-area"
import { Suspense } from "react"
import { LuLoaderCircle } from "react-icons/lu"

async function DocumentReviewContent({
  params,
}: {
  params: Promise<{ documentId: string }>
}) {
  const { documentId } = await params
  return <DocumentReviewArea documentId={documentId} />
}

function DocumentReviewFallback() {
  return (
    <main className="review-page" aria-busy="true">
      <div className="review-state" role="status">
        <LuLoaderCircle className="spin" />
        Loading document review…
      </div>
    </main>
  )
}

export default function DocumentReviewPage({
  params,
}: {
  params: Promise<{ documentId: string }>
}) {
  return (
    <Suspense fallback={<DocumentReviewFallback />}>
      <DocumentReviewContent params={params} />
    </Suspense>
  )
}
