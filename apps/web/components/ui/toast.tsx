"use client";

import clsx from "clsx";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type ToastTone = "info" | "good" | "bad";
type ToastItem = { id: number; message: string; tone: ToastTone };
type Push = (message: string, tone?: ToastTone) => void;

const Ctx = createContext<Push>(() => {});

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback<Push>((message, tone = "info") => {
    const id = ++seq;
    setItems((xs) => [...xs.slice(-2), { id, message, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-6"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            data-testid="toast"
            className={clsx(
              "pointer-events-auto max-w-sm rounded-xl border bg-surface px-3.5 py-2.5 text-sm shadow-lg",
              t.tone === "good" && "border-good/50",
              t.tone === "bad" && "border-bad/50 text-bad",
              t.tone === "info" && "border-border",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): Push {
  return useContext(Ctx);
}
