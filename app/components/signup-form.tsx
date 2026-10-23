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
import { useState, type FormEvent } from "react"
import { z } from "zod"

const signupSchema = z.object({
  username: z
    .string()
    .trim()
    .min(3, "Username must be at least 3 characters.")
    .max(50, "Username must be 50 characters or fewer."),
  email: z.email("Enter a valid email address."),
  password: z.string().min(8, "Password must be at least 8 characters."),
})

type SignupErrors = Partial<Record<"username" | "email" | "password", string>>

export function SignupForm() {
  const [errors, setErrors] = useState<SignupErrors>({})

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const formData = new FormData(event.currentTarget)
    const result = signupSchema.safeParse(Object.fromEntries(formData.entries()))

    if (!result.success) {
      setErrors({
        username: result.error.issues.find(
          (issue) => issue.path[0] === "username",
        )?.message,
        email: result.error.issues.find((issue) => issue.path[0] === "email")
          ?.message,
        password: result.error.issues.find(
          (issue) => issue.path[0] === "password",
        )?.message,
      })
      return
    }

    setErrors({})
  }

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
          <Heading size="xl">Create your account</Heading>
          <Text color="fg.muted">
            Sign up with your username, email, and password.
          </Text>
        </Stack>
        <form noValidate onSubmit={handleSubmit}>
          <Stack gap="4">
            <Field.Root required invalid={Boolean(errors.username)}>
              <Field.Label>Username</Field.Label>
              <Input
                type="text"
                name="username"
                placeholder="Choose a username"
                autoComplete="username"
              />
              {errors.username && (
                <Field.ErrorText>{errors.username}</Field.ErrorText>
              )}
            </Field.Root>
            <Field.Root required invalid={Boolean(errors.email)}>
              <Field.Label>Email</Field.Label>
              <Input
                type="email"
                name="email"
                placeholder="you@example.com"
                autoComplete="email"
              />
              {errors.email && <Field.ErrorText>{errors.email}</Field.ErrorText>}
            </Field.Root>
            <Field.Root required invalid={Boolean(errors.password)}>
              <Field.Label>Password</Field.Label>
              <Input
                type="password"
                name="password"
                placeholder="Enter your password"
                autoComplete="new-password"
              />
              {errors.password && (
                <Field.ErrorText>{errors.password}</Field.ErrorText>
              )}
            </Field.Root>
            <Button type="submit" colorPalette="teal" w="full">
              Create account
            </Button>
          </Stack>
        </form>
        <Text textAlign="center" color="fg.muted">
          Already have an account?{" "}
          <ChakraLink asChild color="teal.fg" fontWeight="medium">
            <NextLink href="/login">Sign in</NextLink>
          </ChakraLink>
        </Text>
      </Stack>
    </Flex>
  )
}
