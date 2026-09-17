import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        workspace: fileURLToPath(new URL("./index.html", import.meta.url)),
        example: fileURLToPath(new URL("./api-example.html", import.meta.url)),
      },
    },
  },
  optimizeDeps: { exclude: ["@rpi360/web-sdk/wasm"] },
});
