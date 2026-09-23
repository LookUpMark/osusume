import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  server: {
    // `pnpm dev` (FastAPI :3000) + `pnpm dev:ui`: api.ts usa path relativi — senza
    // proxy il Vite risponde all'UI con index.html e l'app crasha in silenzio
    proxy: { "/api": `http://127.0.0.1:${process.env.PORT || 3000}` },
  },
});
