import {
  Button,
  FileUpload,
  HStack,
  Heading,
  Icon,
  Spinner,
  Stack,
  Text,
} from "@chakra-ui/react"
import { uploadDocuments } from "@/api/documents"
import { useMutation } from "@tanstack/react-query"
import { LuFile, LuFileSpreadsheet, LuFileText, LuUpload } from "react-icons/lu"
import { useState } from "react"

function DocumentIcon({ file }: { file: File }) {
  const extension = file.name.split(".").pop()?.toLowerCase()
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
  const [uploadingFiles, setUploadingFiles] = useState<Set<string>>(new Set())
  const uploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      uploadDocuments(files, (file, index, uploading) => {
        const key = `${file.name}-${index}`
        setUploadingFiles((current) => {
          const next = new Set(current)
          if (uploading) next.add(key)
          else next.delete(key)
          return next
        })
      }),
  })

  return (
    <Stack w="full" maxW="7xl" gap="6">
      <Stack>
        <Heading size="2xl">Upload documents</Heading>
      </Stack>
      <FileUpload.Root
        maxFiles={10}
        colorPalette="teal"
        onFileChange={({ acceptedFiles }) => {
          if (acceptedFiles.length === 0) {
            uploadMutation.reset()
            setUploadingFiles(new Set())
          }
        }}
      >
        <FileUpload.HiddenInput />
        <FileUpload.Context>
          {({ acceptedFiles }) => (
            <>
              {acceptedFiles.length === 0 ? (
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
                      Up to 10 documents at a time
                    </Text>
                  </FileUpload.DropzoneContent>
                </FileUpload.Dropzone>
              ) : (
                <FileUpload.Trigger asChild>
                  <Button
                    variant="outline"
                    colorPalette="teal"
                    alignSelf="flex-start"
                    disabled={uploadMutation.isPending || uploadMutation.isSuccess}
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
                        <DocumentIcon file={file} />
                      </FileUpload.ItemPreview>
                      <FileUpload.ItemContent>
                        <FileUpload.ItemName />
                        <FileUpload.ItemSizeText />
                        {uploadingFiles.has(`${file.name}-${index}`) && (
                          <HStack gap="2" color="fg.muted">
                            <Spinner size="xs" color="teal.500" />
                            <Text fontSize="sm">Uploading document</Text>
                          </HStack>
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
              {acceptedFiles.length > 0 && (
                <Stack w="full" gap="3">
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
                  <Button
                    alignSelf="flex-start"
                    colorPalette="teal"
                    disabled={uploadMutation.isPending || uploadMutation.isSuccess}
                    onClick={() => uploadMutation.mutate(acceptedFiles)}
                  >
                    {uploadMutation.isPending
                      ? "Uploading documents..."
                      : uploadMutation.isSuccess
                        ? "Upload complete"
                        : "Start processing"}
                  </Button>
                </Stack>
              )}
            </>
          )}
        </FileUpload.Context>
      </FileUpload.Root>
    </Stack>
  )
}
