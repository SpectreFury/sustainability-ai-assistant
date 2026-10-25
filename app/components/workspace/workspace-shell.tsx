"use client"

import { getCurrentUser, logout } from "@/api/auth"
import { useMutation, useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import type { ReactNode } from "react"
import { Suspense, useState } from "react"
import {
  LuCalendarDays,
  LuFileCheck2,
  LuFiles,
  LuFlaskConical,
  LuLogOut,
  LuSparkles,
  LuSprout,
  LuUpload,
} from "react-icons/lu"

type WorkspacePage =
  | "documents"
  | "upload"
  | "ask"
  | "financial-year"
  | "evaluations"

function WorkspaceNavigationLinks({
  activePage,
}: {
  activePage?: WorkspacePage
}) {
  return (
    <nav className="workspace-nav" aria-label="Workspace navigation">
      <Link
        className={`workspace-nav-item ${activePage === "documents" ? "is-active" : ""}`}
        aria-current={activePage === "documents" ? "page" : undefined}
        href="/workspace/documents"
      >
        <LuFiles aria-hidden="true" />
        <span>Documents</span>
      </Link>
      <Link
        className={`workspace-nav-item ${activePage === "upload" ? "is-active" : ""}`}
        aria-current={activePage === "upload" ? "page" : undefined}
        href="/workspace/upload"
      >
        <LuUpload aria-hidden="true" />
        <span>Upload &amp; Processing</span>
      </Link>
      <Link
        className={`workspace-nav-item ${activePage === "ask" ? "is-active" : ""}`}
        aria-current={activePage === "ask" ? "page" : undefined}
        href="/workspace"
      >
        <LuSparkles aria-hidden="true" />
        <span>Ask AI</span>
      </Link>
      <Link
        className={`workspace-nav-item ${activePage === "financial-year" ? "is-active" : ""}`}
        aria-current={activePage === "financial-year" ? "page" : undefined}
        href="/workspace/financial-year"
      >
        <LuCalendarDays aria-hidden="true" />
        <span>Financial-Year Summary</span>
      </Link>
      <Link
        className={`workspace-nav-item ${activePage === "evaluations" ? "is-active" : ""}`}
        aria-current={activePage === "evaluations" ? "page" : undefined}
        href="/workspace/evaluations"
      >
        <LuFlaskConical aria-hidden="true" />
        <span>Evaluations</span>
      </Link>
    </nav>
  )
}

function WorkspaceNavigation() {
  const pathname = usePathname()
  const activePage: WorkspacePage = pathname.startsWith("/workspace/evaluations")
    ? "evaluations"
    : pathname.startsWith("/workspace/documents")
      ? "documents"
      : pathname.startsWith("/workspace/upload")
        ? "upload"
        : pathname.startsWith("/workspace/financial-year")
          ? "financial-year"
          : "ask"

  return <WorkspaceNavigationLinks activePage={activePage} />
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [logoutError, setLogoutError] = useState("")
  const userQuery = useQuery({
    queryKey: ["current-user"],
    queryFn: getCurrentUser,
    retry: false,
  })
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => router.replace("/login"),
    onError: (error) => setLogoutError(error.message),
  })
  const username = userQuery.data?.username ?? "Workspace account"
  const initials = username
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("")
  return (
    <div className="workspace-app">
      <aside className="workspace-sidebar">
        <Link
          className="workspace-brand"
          href="/workspace"
          aria-label="KuKi workspace"
        >
          <span className="workspace-brand-mark">
            <LuSprout aria-hidden="true" />
          </span>
          <span>KuKi</span>
        </Link>

        <div className="workspace-picker">
          <span className="workspace-picker-label">WORKSPACE</span>
          <span className="workspace-picker-name">Your workspace</span>
        </div>

        <Suspense fallback={<WorkspaceNavigationLinks />}>
          <WorkspaceNavigation />
        </Suspense>

        <div className="workspace-account">
          <span className="account-avatar" aria-hidden="true">
            {initials || "WS"}
          </span>
          <span className="account-copy">
            <strong>{username}</strong>
            <span>{userQuery.data?.email ?? "Signed-in workspace"}</span>
          </span>
          <button
            type="button"
            className="icon-button logout-button"
            aria-label={logoutMutation.isPending ? "Signing out" : "Sign out"}
            title="Sign out"
            disabled={logoutMutation.isPending}
            onClick={() => {
              setLogoutError("")
              logoutMutation.mutate(undefined)
            }}
          >
            <LuLogOut aria-hidden="true" />
          </button>
        </div>
        {logoutError && (
          <p className="sidebar-error" role="alert">
            {logoutError}
          </p>
        )}
      </aside>
      <div className="workspace-main">{children}</div>
    </div>
  )
}
