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
import { login } from "@/api/auth"
import { useMutation } from "@tanstack/react-query"
import NextLink from "next/link"
import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"
import { z } from "zod"

const loginSchema = z.object({
  email: z.email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
})

type LoginErrors = Partial<Record<"email" | "password", string>>

export function LoginForm() {
  const [errors, setErrors] = useState<LoginErrors>({})
  const router = useRouter()
  const loginMutation = useMutation({ mutationFn: login })

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    loginMutation.reset()

    const formData = new FormData(event.currentTarget)
    const result = loginSchema.safeParse(Object.fromEntries(formData.entries()))

    if (!result.success) {
      setErrors({
        email: result.error.issues.find((issue) => issue.path[0] === "email")
          ?.message,
        password: result.error.issues.find(
          (issue) => issue.path[0] === "password",
        )?.message,
      })
      return
    }

    setErrors({})

    loginMutation.mutate(result.data, {
      onSuccess: () => router.replace("/workspace"),
    })
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
          <Heading size="xl">Welcome back</Heading>
          <Text color="fg.muted">Sign in with your email and password.</Text>
        </Stack>
        <form noValidate onSubmit={handleSubmit}>
          <Stack gap="4">
            {loginMutation.isError && (
              <Text role="alert" color="red.500">
                {loginMutation.error.message}
              </Text>
            )}
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
                autoComplete="current-password"
              />
              {errors.password && (
                <Field.ErrorText>{errors.password}</Field.ErrorText>
              )}
            </Field.Root>
            <Button
              type="submit"
              colorPalette="teal"
              w="full"
              disabled={loginMutation.isPending}
            >
              {loginMutation.isPending ? "Signing in..." : "Sign in"}
            </Button>
          </Stack>
        </form>
        <Text textAlign="center" color="fg.muted">
          Don&apos;t have an account?{" "}
          <ChakraLink asChild color="teal.fg" fontWeight="medium">
            <NextLink href="/signup">Sign up</NextLink>
          </ChakraLink>
        </Text>
      </Stack>
    </Flex>
  )
}
