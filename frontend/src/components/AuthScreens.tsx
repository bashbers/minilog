import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Baby, LockKeyhole, ShieldCheck } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";

import { api, ApiError } from "../api/client";

function errorText(error: unknown) {
  if (error instanceof ApiError) return error.detail.replaceAll("_", " ");
  return "Could not reach Minilog";
}

export function SetupScreen() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: api.setup,
    onSuccess: async () => {
      await queryClient.invalidateQueries();
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    mutation.mutate({
      setup_token: String(values.get("setupToken")),
      household_name: String(values.get("householdName")),
      time_zone: String(values.get("timeZone")),
      username: String(values.get("username")),
      display_name: String(values.get("displayName")),
      password: String(values.get("password")),
    });
  };
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand-mark"><Baby aria-hidden="true" /></div>
        <p className="eyebrow">Private by default</p>
        <h1>Welcome to Minilog</h1>
        <p className="muted">Create your household and its first Owner. Nothing leaves this server.</p>
        <form onSubmit={submit} className="form-stack">
          <label>Setup token<input name="setupToken" type="password" required minLength={20} /></label>
          <label>Household name<input name="householdName" required defaultValue="Our home" /></label>
          <label>Time zone<input name="timeZone" required defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone} /></label>
          <div className="field-row">
            <label>Username<input name="username" required minLength={3} autoComplete="username" /></label>
            <label>Your name<input name="displayName" required autoComplete="name" /></label>
          </div>
          <label>Password<input name="password" type="password" required minLength={12} autoComplete="new-password" /></label>
          {mutation.isError && <p className="error" role="alert">{errorText(mutation.error)}</p>}
          <button className="primary" disabled={mutation.isPending}><ShieldCheck /> Create private household</button>
        </form>
      </section>
    </main>
  );
}

export function LoginScreen() {
  const [joining, setJoining] = useState(false);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: api.login,
    onSuccess: async () => queryClient.invalidateQueries(),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    mutation.mutate({
      username: String(values.get("username")),
      password: String(values.get("password")),
      device_name: navigator.userAgent.includes("Mobile") ? "Mobile browser" : "Browser",
    });
  };
  const accept = useMutation({
    mutationFn: api.acceptInvitation,
    onSuccess: async () => queryClient.invalidateQueries(),
  });
  const acceptInvite = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    accept.mutate({
      token: String(values.get("token")),
      username: String(values.get("username")),
      display_name: String(values.get("displayName")),
      password: String(values.get("password")),
      device_name: navigator.userAgent.includes("Mobile") ? "Mobile browser" : "Browser",
    });
  };
  return (
    <main className="auth-shell">
      <section className="auth-card compact">
        <div className="brand-mark"><Baby aria-hidden="true" /></div>
        <p className="eyebrow">{joining ? "Join household" : "Minilog"}</p>
        <h1>{joining ? "Use your invitation" : "Good to see you"}</h1>
        <p className="muted">{joining ? "Create a local Caregiver account on this server." : "Sign in to your household."}</p>
        {joining ? <form onSubmit={acceptInvite} className="form-stack">
          <label>Invitation code<input name="token" required minLength={20} autoComplete="off" /></label>
          <label>Username<input name="username" required minLength={3} autoComplete="username" /></label>
          <label>Your name<input name="displayName" required autoComplete="name" /></label>
          <label>Password<input name="password" type="password" required minLength={12} autoComplete="new-password" /></label>
          {accept.isError && <p className="error" role="alert">{errorText(accept.error)}</p>}
          <button className="primary" disabled={accept.isPending}><ShieldCheck /> Join household</button>
        </form> : <form onSubmit={submit} className="form-stack">
          <label>Username<input name="username" required autoComplete="username" /></label>
          <label>Password<input name="password" type="password" required autoComplete="current-password" /></label>
          {mutation.isError && <p className="error" role="alert">{errorText(mutation.error)}</p>}
          <button className="primary" disabled={mutation.isPending}><LockKeyhole /> Sign in</button>
        </form>}
        <button className="auth-switch" onClick={() => setJoining(!joining)}>{joining ? "I already have an account" : "I have an invitation code"}</button>
      </section>
    </main>
  );
}
