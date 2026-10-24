"use client"

import { AskArea } from "@/components/areas/ask-area"
import { useRouter } from "next/navigation"

export default function WorkspacePage() {
  const router = useRouter()
  return <AskArea onNavigateUpload={() => router.push("/workspace/upload")} />
}
