"use client"

import { Button, Flex, Stack } from "@chakra-ui/react"
import { AskArea } from "@/components/areas/ask-area"
import { UploadArea } from "@/components/areas/upload-area"
import { useState } from "react"

type ActiveTab = "upload" | "ask"

export default function WorkspacePage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("upload")
  const ActiveArea = activeTab === "upload" ? UploadArea : AskArea

  return (
    <Flex minH="100dvh" bg="bg.subtle">
      <Stack
        as="nav"
        aria-label="Main navigation"
        w="240px"
        flexShrink="0"
        gap="2"
        p="4"
        borderRightWidth="1px"
        borderColor="border"
        bg="bg"
      >
        <Button
          aria-current={activeTab === "upload" ? "page" : undefined}
          variant={activeTab === "upload" ? "solid" : "ghost"}
          colorPalette="teal"
          justifyContent="flex-start"
          onClick={() => setActiveTab("upload")}
        >
          Upload
        </Button>
        <Button
          aria-current={activeTab === "ask" ? "page" : undefined}
          variant={activeTab === "ask" ? "solid" : "ghost"}
          colorPalette="teal"
          justifyContent="flex-start"
          onClick={() => setActiveTab("ask")}
        >
          Ask
        </Button>
      </Stack>
      <Flex as="main" flex="1" justify="center" p="8">
        <ActiveArea />
      </Flex>
    </Flex>
  )
}
