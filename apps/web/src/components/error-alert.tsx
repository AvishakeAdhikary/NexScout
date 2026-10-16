import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError } from "@/lib/api/client";

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return "Something unexpected happened. Please try again.";
}

export function ErrorAlert({ error, title = "That didn't work" }: { error: unknown; title?: string }) {
  if (!error) return null;
  const fieldErrors = error instanceof ApiError ? (error.problem.errors ?? []) : [];
  return (
    <Alert variant="destructive" role="alert">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        {fieldErrors.length > 0 && (
          <ul className="mt-1 list-disc pl-5">
            {fieldErrors.map((f) => (
              <li key={f.loc.join(".")}>
                {f.loc.slice(1).join(".") || "request"}: {f.msg}
              </li>
            ))}
          </ul>
        )}
        {error instanceof ApiError && error.problem.request_id && (
          <p className="mt-1 text-xs opacity-70">Reference: {error.problem.request_id}</p>
        )}
      </AlertDescription>
    </Alert>
  );
}
