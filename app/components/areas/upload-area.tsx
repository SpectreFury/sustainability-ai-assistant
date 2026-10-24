"use client"

import {
  Button,
  FileUpload,
  Flex,
  HStack,
  Heading,
  Icon,
  Spinner,
  Stack,
  Text,
} from "@chakra-ui/react"
import {
  getDocuments,
  processDocuments,
  uploadDocuments,
  type DocumentRecord,
  type FileUploadStatus,
} from "@/api/documents"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { LuFile, LuFileSpreadsheet, LuFileText, LuUpload } from "react-icons/lu"
import Link from "next/link"
import { useState } from "react"

function fileKey(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function DocumentIcon({ filename }: { filename: string }) {
  const extension = filename.split(".").pop()?.toLowerCase()
  const isPdf = extension === "pdf"
  const isSpreadsheet = ["xlsx", "xls", "csv"].includes(extension ?? "")
  const FileTypeIcon = isPdf
    ? LuFileText
    : isSpreadsheet
      ? LuFileSpreadsheet
      : LuFile

  return (
    <Icon boxSize="5" color={isPdf ? "red.500" : isSpreadsheet ? "green.600" : "fg.muted"}>
      <FileTypeIcon />
    </Icon>
  )
}

export function UploadArea() {
  const [fileStatuses, setFileStatuses] = useState<Record<string, FileUploadStatus>>({})
  const queryClient = useQueryClient()
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: getDocuments,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === "processing")
        ? 3000
        : false,
  })
  const uploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      uploadDocuments(files, (file, status) =>
        setFileStatuses((current) => ({ ...current, [fileKey(file)]: status })),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  })
  const processMutation = useMutation({
    mutationFn: processDocuments,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  })
  const hasDocuments = (documentsQuery.data?.length ?? 0) > 0

  return (
    <Stack w="full" maxW="7xl" gap="6">
      <Stack>
        <Heading size="2xl">Upload documents</Heading>
      </Stack>
      <FileUpload.Root
        disabled={uploadMutation.isPending}
        maxFiles={Number.MAX_SAFE_INTEGER}
        accept={{
          "application/pdf": [".pdf"],
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
            ".xlsx",
          ],
        }}
        colorPalette="teal"
        onFileChange={({ acceptedFiles }) => {
          const acceptedKeys = new Set(acceptedFiles.map(fileKey))
          const filesToUpload = acceptedFiles.filter(
            (file) =>
              fileStatuses[fileKey(file)] !== "uploaded" &&
              fileStatuses[fileKey(file)] !== "uploading",
          )
          setFileStatuses((current) =>
            Object.fromEntries(
              Object.entries(current).filter(([key]) => acceptedKeys.has(key)),
            ),
          )
          if (!uploadMutation.isPending) uploadMutation.reset()
          if (acceptedFiles.length === 0) {
            uploadMutation.reset()
          } else if (filesToUpload.length > 0 && !uploadMutation.isPending) {
            uploadMutation.mutate(filesToUpload)
          }
        }}
      >
        <FileUpload.HiddenInput />
        <FileUpload.Context>
          {({ acceptedFiles }) => {
            return (
            <>
              {acceptedFiles.length === 0 && !hasDocuments ? (
                <FileUpload.Dropzone
                  w="full"
                  minH={{ base: "64", md: "80" }}
                  borderColor="border"
                >
                  <FileUpload.DropzoneContent>
                    <Icon boxSize="8" color="teal.fg">
                      <LuUpload />
                    </Icon>
                    <Text fontWeight="medium">Drag and drop documents here</Text>
                    <Text color="fg.muted">or</Text>
                    <FileUpload.Trigger asChild>
                      <Button variant="outline" colorPalette="teal">
                        Browse documents
                      </Button>
                    </FileUpload.Trigger>
                    <Text color="fg.muted" fontSize="sm">
                      No file-count limit. Uploads run a few at a time.
                    </Text>
                  </FileUpload.DropzoneContent>
                </FileUpload.Dropzone>
              ) : (
                <FileUpload.Trigger asChild>
                  <Button
                    variant="outline"
                    colorPalette="teal"
                    alignSelf="flex-start"
                    disabled={uploadMutation.isPending}
                  >
                    Add documents
                  </Button>
                </FileUpload.Trigger>
              )}
              {acceptedFiles.length > 0 && (
                <FileUpload.ItemGroup w="full">
                  {acceptedFiles.map((file, index) => (
                    <FileUpload.Item
                      key={`${file.name}-${index}`}
                      file={file}
                    >
                      <FileUpload.ItemPreview>
                        <DocumentIcon filename={file.name} />
                      </FileUpload.ItemPreview>
                      <FileUpload.ItemContent>
                        <FileUpload.ItemName />
                        <FileUpload.ItemSizeText />
                        {fileStatuses[fileKey(file)] === "queued" && (
                          <Text fontSize="sm" color="fg.muted">
                            Waiting to upload
                          </Text>
                        )}
                        {fileStatuses[fileKey(file)] === "uploading" && (
                          <HStack gap="2" color="fg.muted">
                            <Spinner size="xs" color="teal.500" />
                            <Text fontSize="sm">Uploading document</Text>
                          </HStack>
                        )}
                        {fileStatuses[fileKey(file)] === "uploaded" && (
                          <Text fontSize="sm" color="green.600">
                            Uploaded
                          </Text>
                        )}
                        {fileStatuses[fileKey(file)] === "failed" && (
                          <Text fontSize="sm" color="red.500">
                            Upload failed
                          </Text>
                        )}
                      </FileUpload.ItemContent>
                      <FileUpload.ItemDeleteTrigger
                        aria-label={`Remove ${file.name}`}
                        disabled={uploadMutation.isPending}
                      />
                    </FileUpload.Item>
                  ))}
                </FileUpload.ItemGroup>
              )}
              {uploadMutation.isError && (
                <Text role="alert" color="red.500">
                  {uploadMutation.error.message}
                </Text>
              )}
              {uploadMutation.isSuccess && (
                <Text role="status" color="green.600">
                  Documents uploaded successfully.
                </Text>
              )}
            </>
            )
          }}
        </FileUpload.Context>
      </FileUpload.Root>
      {documentsQuery.isPending && (
        <Text color="fg.muted">Loading uploaded documents...</Text>
      )}
      {documentsQuery.isError && (
        <Text role="alert" color="red.500">
          {documentsQuery.error.message}
        </Text>
      )}
      {documentsQuery.data && documentsQuery.data.length > 0 && (
        <Stack w="full" gap="3">
          <Heading size="lg">Uploaded documents</Heading>
          {documentsQuery.data.map((document) => (
            <SavedDocumentTile key={document.id} document={document} />
          ))}
          {documentsQuery.data.some((document) => document.status === "pending") && (
            <Button
              alignSelf="flex-start"
              colorPalette="teal"
              onClick={() => processMutation.mutate()}
              loading={processMutation.isPending}
            >
              Start processing
            </Button>
          )}
          {processMutation.isError && (
            <Text role="alert" color="red.500">
              {processMutation.error.message}
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  )
}

function SavedDocumentTile({ document }: { document: DocumentRecord }) {
  return (
    <Flex
      align="center"
      gap="3"
      w="full"
      p="4"
      bg="bg"
      borderWidth="1px"
      borderColor="border"
      borderRadius="l2"
    >
      <DocumentIcon filename={document.filename} />
      <Stack gap="0">
        <Text fontWeight="medium">{document.filename}</Text>
        <HStack gap="2">
          {document.status === "processing" && !document.error_message && (
            <Spinner size="xs" color="yellow.500" />
          )}
          <Text color="fg.muted" fontSize="sm">
            {document.error_message ??
              {
                pending: "Pending processing",
                processing: "Processing",
                success: "Processed",
                failed: "Failed",
              }[document.status]}
          </Text>
        </HStack>
        {document.status === "success" && (
          <Link
            className="document-review-link"
            href={`/workspace/documents/${document.id}`}
          >
            Review extracted facts
          </Link>
        )}
      </Stack>
    </Flex>
  )
}
