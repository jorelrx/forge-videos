import React from "react";

export interface NewVideoFormProps {
  onSubmit: (input: { tema: string; tese: string | null; priority: number; preset: string }) => void;
  disabled?: boolean;
}

export function NewVideoForm({ onSubmit, disabled }: NewVideoFormProps) {
  return <form data-testid="new-video-form" disabled={disabled} onSubmit={(e) => { e.preventDefault(); onSubmit({ tema: "Test", tese: null, priority: 50, preset: "local-recomendado-v1" }); }} />;
}
