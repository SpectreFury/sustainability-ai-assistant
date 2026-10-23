export type DocumentRecord = {
  id: string
  user_id: number
  filename: string
  cloudinary_url: string | null
  cloudinary_public_id: string
  status: "pending" | "processing" | "success" | "failed"
  error_message: string | null
  upload_timestamp: string
}

type UploadSignature = {
  document_id: string
  upload_url: string
  api_key: string
  timestamp: number
  public_id: string
  signature: string
}

type CloudinaryUpload = {
  public_id: string
  secure_url: string
}

export type FileUploadStatus = "uploading" | "uploaded" | "failed"

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL

export async function getDocuments(): Promise<DocumentRecord[]> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

  const response = await fetch(`${backendUrl}/documents`, {
    credentials: "include",
  })
  if (!response.ok) throw new Error("Unable to load documents.")
  return response.json()
}

export async function processDocuments(): Promise<DocumentRecord[]> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

  const response = await fetch(`${backendUrl}/documents/process`, {
    method: "POST",
    credentials: "include",
  })
  if (!response.ok) {
    const result = await response.json().catch(() => null)
    throw new Error(
      typeof result?.detail === "string"
        ? result.detail
        : "Unable to start document processing.",
    )
  }
  return response.json()
}

export async function uploadDocuments(
  files: File[],
  onFileStatus?: (file: File, status: FileUploadStatus) => void,
): Promise<DocumentRecord[]> {
  if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

  const results = await Promise.allSettled(
    files.map(async (file) => {
      let signature: UploadSignature | undefined
      onFileStatus?.(file, "uploading")

      try {
        const digest = await crypto.subtle.digest(
          "SHA-256",
          await file.arrayBuffer(),
        )
        const fileHash = Array.from(new Uint8Array(digest), (byte) =>
          byte.toString(16).padStart(2, "0"),
        ).join("")
        const signatureResponse = await fetch(
          `${backendUrl}/documents/upload-signature`,
          {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: file.name, file_hash: fileHash }),
          },
        )

        if (!signatureResponse.ok) {
          const result = await signatureResponse.json().catch(() => null)
          throw new Error(
            typeof result?.detail === "string"
              ? result.detail
              : "Unable to prepare the upload.",
          )
        }

        signature = (await signatureResponse.json()) as UploadSignature
        const formData = new FormData()
        formData.append("file", file)
        formData.append("api_key", signature.api_key)
        formData.append("timestamp", String(signature.timestamp))
        formData.append("public_id", signature.public_id)
        formData.append("signature", signature.signature)

        const cloudinaryResponse = await fetch(signature.upload_url, {
          method: "POST",
          body: formData,
        })

        if (!cloudinaryResponse.ok) {
          const result = await cloudinaryResponse.json().catch(() => null)
          throw new Error(
            typeof result?.error?.message === "string"
              ? result.error.message
              : `Unable to upload ${file.name}.`,
          )
        }

        const cloudinaryUpload =
          (await cloudinaryResponse.json()) as CloudinaryUpload
        const completeResponse = await fetch(
          `${backendUrl}/documents/${signature.document_id}/complete`,
          {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              cloudinary_url: cloudinaryUpload.secure_url,
              cloudinary_public_id: cloudinaryUpload.public_id,
            }),
          },
        )

        if (!completeResponse.ok) {
          throw new Error(`Unable to save ${file.name}.`)
        }

        onFileStatus?.(file, "uploaded")
        return (await completeResponse.json()) as DocumentRecord
      } catch (error) {
        if (signature) {
          await fetch(`${backendUrl}/documents/${signature.document_id}/failed`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              error_message:
                error instanceof Error
                  ? error.message.slice(0, 2000)
                  : "Upload failed.",
            }),
          }).catch(() => undefined)
        }

        onFileStatus?.(file, "failed")
        throw error
      }
    }),
  )

  const failedUpload = results.find(
    (result): result is PromiseRejectedResult => result.status === "rejected",
  )
  if (failedUpload) {
    throw failedUpload.reason instanceof Error
      ? failedUpload.reason
      : new Error("One or more documents failed to upload.")
  }

  return results.flatMap((result) =>
    result.status === "fulfilled" ? [result.value] : [],
  )
}
