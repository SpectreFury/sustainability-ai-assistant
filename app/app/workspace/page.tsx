"use client"

import { logout } from "@/api/auth"
import { AskArea } from "@/components/areas/ask-area"
import { UploadArea } from "@/components/areas/upload-area"
import { Button, Flex, Stack, Text } from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useState } from "react"

type ActiveTab = "upload" | "ask"

export default function WorkspacePage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("upload")
  const router = useRouter()
  const logoutMutation = useMutation({ mutationFn: logout })
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
        minH="100dvh"
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
        {logoutMutation.isError && (
          <Text role="alert" color="red.500">
            {logoutMutation.error.message}
          </Text>
        )}
        <Button
          mt="auto"
          variant="ghost"
          colorPalette="red"
          justifyContent="flex-start"
          disabled={logoutMutation.isPending}
          onClick={() =>
            logoutMutation.mutate(undefined, {
              onSuccess: () => router.replace("/login"),
            })
          }
        >
          {logoutMutation.isPending ? "Logging out..." : "Log out"}
        </Button>
      </Stack>
      <Flex as="main" flex="1" justify="center" p="8">
        <ActiveArea />
      </Flex>
    </Flex>
  )
}
