"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authApi } from "@/lib/api/client";
import { safeNext } from "@/lib/sections";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const isRegister = mode === "register";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setPending(true);
    setError(null);
    try {
      if (isRegister) {
        await authApi.register(email, password, String(form.get("display_name") ?? ""));
      } else {
        await authApi.login(email, password);
      }
      // Next keeps visited routes mounted (hidden) for instant back navigation; don't leave
      // the password sitting in a hidden input.
      formElement.reset();
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (err) {
      setError(err);
      setPending(false);
    }
  }

  return (
    <Card className="animate-page w-full max-w-sm shadow-2xl shadow-primary/10 backdrop-blur">
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl font-semibold">
            {isRegister ? "Create your NexScout account" : "Sign in to NexScout"}
          </h1>
        </CardTitle>
        <CardDescription>
          {isRegister
            ? "Your data stays private to your account. You can export or delete it any time."
            : "Welcome back."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate={false}>
          {isRegister && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="display_name">Your name</Label>
              <Input id="display_name" name="display_name" required maxLength={120} autoComplete="name" />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" required autoComplete="email" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              required
              minLength={isRegister ? 12 : undefined}
              maxLength={256}
              autoComplete={isRegister ? "new-password" : "current-password"}
              aria-describedby={isRegister ? "password-help" : undefined}
            />
            {isRegister && (
              <p id="password-help" className="text-xs text-muted-foreground">
                At least 12 characters. A passphrase of a few words works well.
              </p>
            )}
          </div>
          <ErrorAlert error={error} />
          <Button type="submit" disabled={pending}>
            {pending ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
          </Button>
          <p className="text-sm text-muted-foreground">
            {isRegister ? (
              <>
                Already have an account? <Link className="underline" href="/login">Sign in</Link>
              </>
            ) : (
              <>
                New here? <Link className="underline" href="/register">Create an account</Link>
              </>
            )}
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
