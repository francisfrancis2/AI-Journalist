"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchInterval: (query) => {
              // Auto-refetch in-progress stories every 5 seconds
              const data = query.state.data as { status?: string } | undefined;
              const activeStatuses = [
                "pending",
                "researching",
                "analysing",
                "writing_storyline",
                "evaluating",
                "scripting",
              ];
              if (data?.status && activeStatuses.includes(data.status)) {
                return 5_000;
              }
              return false;
            },
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
