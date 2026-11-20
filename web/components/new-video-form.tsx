"use client";
import React, { forwardRef, useState } from "react";
import type { CreateVideoRequest } from "../lib/contracts";

export interface NewVideoFormProps {
  onSubmit: (input: CreateVideoRequest) => void | Promise<void>;
  disabled?: boolean;
}

export const NewVideoForm = forwardRef<HTMLFormElement, NewVideoFormProps>(
  function NewVideoForm({ onSubmit, disabled }, ref) {
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
      <form
        ref={ref}
        className="video-form"
        data-testid="new-video-form"
        onSubmit={handleSubmit}
      >
        <fieldset disabled={disabled}>
          <div className="field">
            <label htmlFor="tema">Tema</label>
            <input
              id="tema"
              name="tema"
              type="text"
              autoComplete="off"
              placeholder="Ex.: Por que adiamos o que importa"
              value={tema}
              onChange={(event) => setTema(event.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tese">
              Tese opcional
            </label>
            <textarea
              id="tese"
              name="tese"
              rows={3}
              aria-describedby="tese-hint"
              value={tese}
              onChange={(event) => setTese(event.target.value)}
            />
            <small id="tese-hint" className="field-hint">
              Em branco, o planejamento escolhe a tese que o acervo sustenta.
            </small>
          </div>
          <div className="form-row">
            <div className="field field-priority">
              <label htmlFor="priority">Prioridade</label>
              <input
                id="priority"
                name="priority"
                type="number"
                inputMode="numeric"
                min="0"
                max="100"
                value={priority}
                onChange={(event) => setPriority(Number(event.target.value))}
              />
            </div>
            <button className="btn btn-primary btn-block" type="submit">
              Enfileirar vídeo
            </button>
          </div>
        </fieldset>
      </form>
    );
  },
);
