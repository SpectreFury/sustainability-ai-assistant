type LoginPayload = {
  email: string
  password: string
}

type SignupPayload = LoginPayload & {
  username: string
}

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL

export async function login(data: LoginPayload) {
  if (!backendUrl) {
    throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  }

  const response = await fetch(`${backendUrl}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    const result = await response.json().catch(() => null)
    throw new Error(
      typeof result?.detail === "string" ? result.detail : "Unable to sign in.",
    )
  }
}

export async function signup(data: SignupPayload) {
  if (!backendUrl) {
    throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  }

  const response = await fetch(`${backendUrl}/auth/signup`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    const result = await response.json().catch(() => null)
    throw new Error(
      typeof result?.detail === "string" ? result.detail : "Unable to sign up.",
    )
  }
}

export async function logout() {
  if (!backendUrl) {
    throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")
  }

  const response = await fetch(`${backendUrl}/auth/logout`, {
    method: "POST",
    credentials: "include",
  })

  if (!response.ok) {
    throw new Error("Unable to log out.")
  }
}
