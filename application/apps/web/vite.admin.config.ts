import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Separate build and HTTP route inventory: never a business-SPA entry point.
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist-admin",
    sourcemap: false,
    lib: {
      entry: "src/admin/main.tsx",
      formats: ["es"],
      fileName: () => "admin.js",
      cssFileName: "admin",
    },
  },
});
