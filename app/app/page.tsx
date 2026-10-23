import { ChakraTest } from "@/components/chakra-test"
import { Flex } from "@chakra-ui/react"

export default function Home() {
  return (
    <Flex minH="100dvh" align="center" justify="center">
      <ChakraTest />
    </Flex>
  )
}
