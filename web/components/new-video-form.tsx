"use client";
import React, { useState } from "react";
import type { CreateVideoRequest } from "../lib/contracts";

export interface NewVideoFormProps {
  onSubmit: (input: CreateVideoRequest) => void | Promise<void>;
  disabled?: boolean;
}

export function NewVideoForm({ onSubmit, disabled }: NewVideoFormProps) {
  const [tema, setTema] = useState("");
  const [tese, setTese] = useState("");
  const [priority, setPriority] = useState(50);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTema = tema.trim();
    if (!normalizedTema) return;
    const normalizedTese = tese.trim();
    onSubmit({
      tema: normalizedTema,
      tese: normalizedTese || null,
      priority,
      preset: "local-recomendado-v1",
    });
  }

  return (
    <form data-testid="new-video-form" onSubmit={handleSubmit}>
      <fieldset disabled={disabled}>
        <label htmlFor="tema">Tema</label>
        <input
          id="tema"
          name="tema"
          value={tema}
          onChange={(event) => setTema(event.target.value)}
          required
        />
        <label htmlFor="tese">Tese opcional</label>
        <textarea
          id="tese"
          name="tese"
          value={tese}
          onChange={(event) => setTese(event.target.value)}
        />
        <label htmlFor="priority">Prioridade</label>
        <input
          id="priority"
          name="priority"
          type="number"
          min="0"
          max="100"
          value={priority}
          onChange={(event) => setPriority(Number(event.target.value))}
        />
        <button type="submit">Enfileirar vídeo</button>
      </fieldset>
    </form>
  );
}
