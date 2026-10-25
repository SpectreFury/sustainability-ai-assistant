"use client"

import { getDocuments, type DocumentRecord } from "@/api/documents"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import {
  LuArrowRight,
  LuFileCheck2,
  LuFileSpreadsheet,
  LuFileText,
  LuLoaderCircle,
  LuTriangleAlert,
  LuUpload,
} from "react-icons/lu"

function DocumentTypeIcon({ filename }: { filename: string }) {
  const extension = filename.split(".").pop()?.toLowerCase()
  if (extension === "pdf") return <LuFileText aria-hidden="true" />
  if (extension === "xlsx") return <LuFileSpreadsheet aria-hidden="true" />
  return <LuFileCheck2 aria-hidden="true" />
}

function statusText(document: DocumentRecord) {
  if (document.error_message) return document.error_message
  if (
    document.status === "processing" &&
    document.chunks_total !== null &&
    document.chunks_total !== undefined &&
    document.chunks_total > 1
  ) {
    return `${document.chunks_completed ?? 0} of ${document.chunks_total} chunks`
  }
  return {
    pending: "Waiting to process",
    processing: "Processing document",
    success: "Ready for review",
    failed: "Processing failed",
  }[document.status]
}

export function DocumentsArea() {
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: getDocuments,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === "processing")
        ? 3000
        : false,
  })
  const documents = documentsQuery.data ?? []

  return (
    <main className="documents-page">
      <header className="documents-topbar">
        <div className="review-breadcrumb">
          <Link href="/workspace">Workspace</Link>
          <span aria-hidden="true">/</span>
          <strong>Documents</strong>
        </div>
      </header>

      <div className="documents-content">
        <div className="documents-title-row">
          <div>
            <h1>Documents</h1>
            <p>Review extracted facts and follow each value back to its source.</p>
          </div>
          <Link className="button button-primary" href="/workspace/upload">
            <LuUpload aria-hidden="true" />
            Upload documents
          </Link>
        </div>

        {documentsQuery.isPending && (
          <div className="documents-state" role="status">
            <LuLoaderCircle className="spin" aria-hidden="true" />
            Loading documents…
          </div>
        )}
        {documentsQuery.isError && (
          <div className="documents-state is-error" role="alert">
            <LuTriangleAlert aria-hidden="true" />
            {documentsQuery.error.message}
          </div>
        )}
        {documentsQuery.data && documents.length === 0 && (
          <section className="documents-empty">
            <span className="documents-empty-icon">
              <LuFileCheck2 aria-hidden="true" />
            </span>
            <h2>No documents yet</h2>
            <p>Upload a bill, workbook, waste record, or sustainability policy to get started.</p>
            <Link className="button button-primary" href="/workspace/upload">
              Upload a document <LuArrowRight aria-hidden="true" />
            </Link>
          </section>
        )}
        {documents.length > 0 && (
          <section className="documents-list" aria-label="Uploaded documents">
            {documents.map((document) => (
              <article className="document-list-card" key={document.id}>
                <span className="document-type-icon">
                  <DocumentTypeIcon filename={document.filename} />
                </span>
                <div className="document-list-copy">
                  <strong>{document.filename}</strong>
                  <span>
                    {new Date(document.upload_timestamp).toLocaleDateString(undefined, {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                    {" · "}
                    {statusText(document)}
                  </span>
                </div>
                {document.status === "success" ? (
                  <Link
                    className="button button-outline button-small"
                    href={`/workspace/documents/${document.id}`}
                  >
                    Review facts <LuArrowRight aria-hidden="true" />
                  </Link>
                ) : (
                  <span className={`document-status status-${document.status}`}>
                    {document.status === "processing" && (
                      <LuLoaderCircle className="spin" aria-hidden="true" />
                    )}
                    {document.status}
                  </span>
                )}
              </article>
            ))}
          </section>
        )}
      </div>
    </main>
  )
}
