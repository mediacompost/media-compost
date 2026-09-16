import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on Uvicorn (8000) in dev; proxy /api so the SPA can use
// same-origin relative URLs in both dev and the bundled production build.
//
// `MC_DEV_API` points it somewhere else — which is how the SPA is driven
// against a second library (a seeded big one, say) WITHOUT rebuilding
// `_web_dist` under whatever server is already open on 8000: that rebuild
// puts the update banner over every tab it is serving and refuses their
// writes until they reload.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.MC_DEV_API ?? "http://127.0.0.1:8000",
    },
  },
  build: {
    // `_dist`, not `dist`: a generated directory is named `_something` in this
    // repository (see .gitignore), so it is tellable from the source tree at a
    // glance. `scripts/build.sh` copies it to `media_compost/ui/_web_dist`.
    outDir: "_dist",
  },
});
