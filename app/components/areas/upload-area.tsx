import {
  Button,
  FileUpload,
  Heading,
  Icon,
  Stack,
  Text,
} from "@chakra-ui/react"
import { LuFile, LuFileSpreadsheet, LuFileText, LuUpload } from "react-icons/lu"

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
  return (
    <Stack w="full" maxW="7xl" gap="6">
      <Stack>
        <Heading size="2xl">Upload documents</Heading>
      </Stack>
      <FileUpload.Root maxFiles={10} colorPalette="teal">
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
                  <Button variant="outline" colorPalette="teal" alignSelf="flex-start">
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
                      </FileUpload.ItemContent>
                      <FileUpload.ItemDeleteTrigger
                        aria-label={`Remove ${file.name}`}
                      />
                    </FileUpload.Item>
                  ))}
                </FileUpload.ItemGroup>
              )}
            </>
          )}
        </FileUpload.Context>
      </FileUpload.Root>
    </Stack>
  )
}
