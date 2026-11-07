"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { AnglesProvider } from "@/components/studio/angles-dialog";
import { ToastProvider } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";

function useServiceWorker() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    // In dev, asset URLs are not content-hashed, so the worker serves them network-first (see public/sw.js).
    const dev = process.env.NODE_ENV !== "production";
    navigator.serviceWorker.register(dev ? "/sw.js?dev=1" : "/sw.js", { scope: "/" }).catch(() => {
      /* PWA is progressive: the app works without the worker */
    });
  }, []);
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2,
          },
        },
      }),
  );
  useServiceWorker();
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AnglesProvider>{children}</AnglesProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
