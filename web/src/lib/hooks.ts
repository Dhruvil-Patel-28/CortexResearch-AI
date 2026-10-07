"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Fetched<T> {
  data: T | undefined;
  error: string | null;
}

/**
 * Minimal data-fetching hook: runs `fn` when deps change, keeps the previous
 * value while refetching, and exposes a manual reload.
 *
 * `loading` is derived by comparing the key of the request in flight with the
 * key that produced the current data, so no state is set synchronously inside
 * an effect (React's set-state-in-effect rule).
 *
 * Deliberately dependency-free — the app talks to a local API, so a small hook
 * beats pulling in a data library.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const fnRef = useRef(fn);

  // Keep the freshest fetcher without making it a request dependency.
  useEffect(() => {
    fnRef.current = fn;
  });

  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  const key = JSON.stringify(deps) + `#${tick}`;

  const [result, setResult] = useState<Fetched<T>>({ data: undefined, error: null });
  const [settledKey, setSettledKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const current = key;

    fnRef
      .current()
      .then((data) => {
        if (cancelled) return;
        setResult({ data, error: null });
        setSettledKey(current);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult({
          data: undefined,
          error: err instanceof Error ? err.message : "Request failed",
        });
        setSettledKey(current);
      });

    return () => {
      cancelled = true;
    };
  }, [key]);

  return { ...result, loading: settledKey !== key, reload };
}

/** Debounce any fast-changing value (search boxes). */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}
