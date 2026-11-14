import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL("./central", import.meta.url)),
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: fileURLToPath(new URL("../server/app/central_build/dist", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
});
