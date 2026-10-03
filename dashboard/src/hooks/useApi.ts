import { useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";

interface ApiOptions {
  headers?: Record<string, string>;
}

export function useApi() {
  const { mode, token, apiKey } = useAuth();

  const makeHeaders = useCallback(
    (extra?: Record<string, string>): Record<string, string> => {
      const base: Record<string, string> = { "Content-Type": "application/json" };
      if (mode === "google" && token) {
        base["Authorization"] = `Bearer ${token}`;
      } else if (mode === "demo" && apiKey) {
        base["X-API-Key"] = apiKey;
      }
      return { ...base, ...extra };
    },
    [mode, token, apiKey]
  );

  const get = useCallback(
    async <T = unknown>(path: string, options?: ApiOptions): Promise<T> => {
      const res = await fetch(path, {
        headers: makeHeaders(options?.headers),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body?.detail || body?.message || "Request failed", body);
      }
      return res.json() as Promise<T>;
    },
    [makeHeaders]
  );

  const post = useCallback(
    async <T = unknown>(path: string, body?: unknown, options?: ApiOptions): Promise<T> => {
      const res = await fetch(path, {
        method: "POST",
        headers: makeHeaders(options?.headers),
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new ApiError(res.status, errBody?.detail || errBody?.message || "Request failed", errBody);
      }
      return res.json() as Promise<T>;
    },
    [makeHeaders]
  );

  const postForm = useCallback(
    async <T = unknown>(path: string, formData: FormData): Promise<T> => {
      const headers: Record<string, string> = {};
      if (mode === "google" && token) headers["Authorization"] = `Bearer ${token}`;
      else if (mode === "demo" && apiKey) headers["X-API-Key"] = apiKey;

      const res = await fetch(path, { method: "POST", headers, body: formData });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new ApiError(res.status, errBody?.detail || errBody?.message || "Upload failed", errBody);
      }
      return res.json() as Promise<T>;
    },
    [mode, token, apiKey]
  );

  const patch = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> => {
      const res = await fetch(path, {
        method: "PATCH",
        headers: makeHeaders(),
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new ApiError(res.status, errBody?.detail || errBody?.message || "Request failed", errBody);
      }
      return res.json() as Promise<T>;
    },
    [makeHeaders]
  );

  return { get, post, postForm, patch, makeHeaders };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}
