"use client"

import { getCurrentUser, logout } from "@/api/auth"
import { AskArea } from "@/components/areas/ask-area"
import { UploadArea } from "@/components/areas/upload-area"
import {
  LuFiles,
  LuLogOut,
  LuSparkles,
  LuSprout,
  LuUpload,
} from "react-icons/lu"
import Link from "next/link"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useState } from "react"

type ActiveTab = "upload" | "ask"

export default function WorkspacePage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("ask")
  const router = useRouter()
  const logoutMutation = useMutation({ mutationFn: logout })
  const userQuery = useQuery({
    queryKey: ["current-user"],
    queryFn: getCurrentUser,
    retry: false,
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

        <nav className="workspace-nav" aria-label="Workspace navigation">
          <button
            type="button"
            className={`workspace-nav-item ${activeTab === "upload" ? "is-active" : ""}`}
            aria-current={activeTab === "upload" ? "page" : undefined}
            onClick={() => setActiveTab("upload")}
          >
            <LuUpload aria-hidden="true" />
            <span>Upload &amp; Processing</span>
          </button>
          <button
            type="button"
            className={`workspace-nav-item ${activeTab === "ask" ? "is-active" : ""}`}
            aria-current={activeTab === "ask" ? "page" : undefined}
            onClick={() => setActiveTab("ask")}
          >
            <LuSparkles aria-hidden="true" />
            <span>Ask AI</span>
          </button>
        </nav>

        <div className="workspace-promise">
          <LuFiles aria-hidden="true" />
          <strong>Every answer, anchored.</strong>
          <p>Trace a number back to the document it came from.</p>
        </div>

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
            onClick={() =>
              logoutMutation.mutate(undefined, {
                onSuccess: () => router.replace("/login"),
              })
            }
          >
            <LuLogOut aria-hidden="true" />
          </button>
        </div>
        {logoutMutation.isError && (
          <p className="sidebar-error" role="alert">
            {logoutMutation.error.message}
          </p>
        )}
      </aside>

      <div className={`workspace-main ${activeTab === "ask" ? "is-ask" : "is-upload"}`}>
        {activeTab === "ask" ? (
          <AskArea onNavigateUpload={() => setActiveTab("upload")} />
        ) : (
          <main className="upload-content">
            <UploadArea />
          </main>
        )}
      </div>
    </div>
  )
}
