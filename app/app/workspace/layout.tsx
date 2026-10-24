import { WorkspaceShell } from "@/components/workspace/workspace-shell"
import type { ReactNode } from "react"

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: ReactNode
}>) {
  return <WorkspaceShell>{children}</WorkspaceShell>
}
