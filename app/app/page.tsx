"use client"

import { Button, Flex, Heading, Stack, Text } from "@chakra-ui/react"
import { useState } from "react"

type ActiveTab = "upload" | "ask"

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("upload")

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
      <Flex as="main" flex="1" align="center" justify="center" p="8">
        <Stack gap="2" textAlign="center">
          <Heading size="2xl">
            {activeTab === "upload" ? "Upload" : "Ask"}
          </Heading>
          <Text color="fg.muted">
            {activeTab === "upload"
              ? "This is the upload area."
              : "This is the Ask area."}
          </Text>
        </Stack>
      </Flex>
    </Flex>
  )
}
