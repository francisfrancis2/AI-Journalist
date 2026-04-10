"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Register tab is now part of the unified login page
export default function RegisterPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/login"); }, [router]);
  return null;
}
