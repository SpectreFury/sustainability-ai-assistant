"use client"

import {
  Button,
  Field,
  Flex,
  Heading,
  Input,
  Link as ChakraLink,
  Stack,
  Text,
} from "@chakra-ui/react"
import NextLink from "next/link"

type AuthPageProps = {
  mode: "login" | "signup"
}

export function AuthPage({ mode }: AuthPageProps) {
  const isSignup = mode === "signup"

  return (
    <Flex
      minH="100dvh"
      align="center"
      justify="center"
      bg="bg.subtle"
      p="6"
    >
      <Stack
        w="full"
        maxW="sm"
        gap="6"
        p="8"
        bg="bg"
        borderWidth="1px"
        borderColor="border"
        borderRadius="xl"
        boxShadow="sm"
      >
        <Stack gap="2">
          <Heading size="xl">
            {isSignup ? "Create your account" : "Welcome back"}
          </Heading>
          <Text color="fg.muted">
            {isSignup
              ? "Sign up with your email and password."
              : "Sign in with your email and password."}
          </Text>
        </Stack>
        <form onSubmit={(event) => event.preventDefault()}>
          <Stack gap="4">
            <Field.Root required>
              <Field.Label>Email</Field.Label>
              <Input
                type="email"
                name="email"
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field.Root>
            <Field.Root required>
              <Field.Label>Password</Field.Label>
              <Input
                type="password"
                name="password"
                placeholder="Enter your password"
                autoComplete={isSignup ? "new-password" : "current-password"}
              />
            </Field.Root>
            <Button type="submit" colorPalette="teal" w="full">
              {isSignup ? "Create account" : "Sign in"}
            </Button>
          </Stack>
        </form>
        <Text textAlign="center" color="fg.muted">
          {isSignup ? "Already have an account?" : "Don't have an account?"}{" "}
          <ChakraLink asChild color="teal.fg" fontWeight="medium">
            <NextLink href={isSignup ? "/login" : "/signup"}>
              {isSignup ? "Sign in" : "Sign up"}
            </NextLink>
          </ChakraLink>
        </Text>
      </Stack>
    </Flex>
  )
}
