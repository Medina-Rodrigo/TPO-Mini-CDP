import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes the finished site into backend/static, where FastAPI
// serves it. One deploy, one URL, and no cross-origin (CORS) setup needed.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/static", emptyOutDir: true },
});
