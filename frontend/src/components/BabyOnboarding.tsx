import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Baby } from "lucide-react";
import type { FormEvent } from "react";

import { api } from "../api/client";

export function BabyOnboarding() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: api.createBaby,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["babies"] }),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    mutation.mutate({
      display_name: String(values.get("name")),
      birth_date: String(values.get("birthDate")),
      due_date: values.get("dueDate") ? String(values.get("dueDate")) : null,
    });
  };
  return (
    <main className="auth-shell">
      <section className="auth-card compact">
        <div className="brand-mark"><Baby /></div>
        <p className="eyebrow">One last detail</p>
        <h1>Who are we logging for?</h1>
        <form onSubmit={submit} className="form-stack">
          <label>Baby's display name<input name="name" required autoFocus /></label>
          <label>Birth date<input name="birthDate" type="date" required /></label>
          <label>Due date <span className="muted">optional</span><input name="dueDate" type="date" /></label>
          <button className="primary" disabled={mutation.isPending}>Create Baby</button>
        </form>
      </section>
    </main>
  );
}

