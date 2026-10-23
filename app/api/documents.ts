type UploadSignature = {
  upload_url: string
  api_key: string
  timestamp: number
  folder: string
  signature: string
}

export async function uploadDocuments(
  files: File[],
  onFileUpload?: (file: File, index: number, uploading: boolean) => void,
) {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL
  if (!backendUrl) {
    throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  }

  const signatureResponse = await fetch(
    `${backendUrl}/documents/upload-signature`,
    { method: "POST", credentials: "include" },
  )

  if (!signatureResponse.ok) {
    const result = await signatureResponse.json().catch(() => null)
    throw new Error(
      typeof result?.detail === "string"
        ? result.detail
        : "Unable to prepare the upload.",
    )
  }

  const signature = (await signatureResponse.json()) as UploadSignature

  return Promise.all(
    files.map(async (file, index) => {
      onFileUpload?.(file, index, true)
      const formData = new FormData()
      formData.append("file", file)
      formData.append("api_key", signature.api_key)
      formData.append("timestamp", String(signature.timestamp))
      formData.append("folder", signature.folder)
      formData.append("signature", signature.signature)

      try {
        const response = await fetch(signature.upload_url, {
          method: "POST",
          body: formData,
        })

        if (!response.ok) {
          const result = await response.json().catch(() => null)
          throw new Error(
            typeof result?.error?.message === "string"
              ? result.error.message
              : `Unable to upload ${file.name}.`,
          )
        }

        return response.json()
      } finally {
        onFileUpload?.(file, index, false)
      }
    }),
  )
}
