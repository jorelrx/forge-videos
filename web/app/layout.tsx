import type { Metadata, Viewport } from "next";
import { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forge Studio",
  description: "Catálogo, indicadores, produção e publicação dos seus canais.",
};

export const viewport: Viewport = {
  themeColor: "#090a1b",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
