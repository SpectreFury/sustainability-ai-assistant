"use client"

import { ColorModeButton } from "@/components/ui/color-mode"
import {
  Badge,
  Button,
  Card,
  Heading,
  HStack,
  Stack,
  Text,
} from "@chakra-ui/react"
import { useState } from "react"

export function ChakraTest() {
  const [count, setCount] = useState(0)

  return (
    <Card.Root maxW="md" w="full" mx="4">
      <Card.Header>
        <HStack justify="space-between">
          <Heading size="lg">Chakra UI is working</Heading>
          <ColorModeButton />
        </HStack>
      </Card.Header>
      <Card.Body>
        <Stack gap="4">
          <Badge colorPalette="green" alignSelf="flex-start">
            Connected
          </Badge>
          <Text color="fg.muted">
            If this card is styled and the button responds, Chakra UI and
            Emotion are configured correctly.
          </Text>
          <Button onClick={() => setCount((value) => value + 1)}>
            Clicked {count} {count === 1 ? "time" : "times"}
          </Button>
        </Stack>
      </Card.Body>
    </Card.Root>
  )
}
