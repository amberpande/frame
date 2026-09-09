import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so CORS never enters the picture.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
