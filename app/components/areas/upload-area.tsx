import {
  Button,
  FileUpload,
  Heading,
  Icon,
  Stack,
  Text,
} from "@chakra-ui/react"
import { LuUpload } from "react-icons/lu"

export function UploadArea() {
  return (
    <Stack w="full" maxW="7xl" gap="6">
      <Stack>
        <Heading size="2xl">Upload documents</Heading>
      </Stack>
      <FileUpload.Root maxFiles={10} colorPalette="teal">
        <FileUpload.HiddenInput />
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
        <FileUpload.List showSize clearable />
      </FileUpload.Root>
    </Stack>
  )
}
