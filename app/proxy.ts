import { NextResponse, type NextRequest } from "next/server"

const authPages = new Set(["/", "/login", "/signup"])

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isAuthPage = authPages.has(pathname)
  const accessToken = request.cookies.get("access_token")?.value
  const refreshToken = request.cookies.get("refresh_token")?.value

  if (accessToken) {
    return isAuthPage
      ? NextResponse.redirect(new URL("/workspace", request.url))
      : NextResponse.next()
  }

  if (refreshToken) {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL
    if (!backendUrl) throw new Error("NEXT_PUBLIC_BACKEND_URL is not set.")

    const refreshResponse = await fetch(`${backendUrl}/auth/refresh`, {
      method: "POST",
      headers: { cookie: request.headers.get("cookie") ?? "" },
    })

    if (refreshResponse.ok) {
      const response = isAuthPage
        ? NextResponse.redirect(new URL("/workspace", request.url))
        : NextResponse.next()
      const accessCookie = refreshResponse.headers.get("set-cookie")
      if (accessCookie) response.headers.append("set-cookie", accessCookie)
      return response
    }

    const response = isAuthPage
      ? NextResponse.next()
      : NextResponse.redirect(new URL("/login", request.url))
    response.cookies.set("refresh_token", "", { path: "/", maxAge: 0 })
    return response
  }

  return isAuthPage
    ? NextResponse.next()
    : NextResponse.redirect(new URL("/login", request.url))
}

export const config = {
  matcher: ["/", "/login", "/signup", "/workspace/:path*"],
}
