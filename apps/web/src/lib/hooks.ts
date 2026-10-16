"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { ApiError, authApi, casesApi } from "./api/client";

/** Current user; redirects to /login when the backend says the session is invalid. */
export function useMe() {
  const router = useRouter();
  const pathname = usePathname();
  const query = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const unauthenticated = query.error instanceof ApiError && query.error.status === 401;
  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, router, pathname]);
  return query;
}

export function useCases() {
  return useQuery({ queryKey: ["cases"], queryFn: casesApi.list });
}

export function useCase(caseId: string) {
  return useQuery({ queryKey: ["cases", caseId], queryFn: () => casesApi.get(caseId) });
}
