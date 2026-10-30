import vinext from "vinext";
import { defineConfig } from "vite";

// macOS Seatbelt blocks FSEvents, so Codex previews need polling for HMR.
const isCodexSeatbeltSandbox = process.env.CODEX_SANDBOX === "seatbelt";

export default defineConfig({
  server: isCodexSeatbeltSandbox
    ? { watch: { useFsEvents: false, usePolling: true } }
    : undefined,
  // Production is a standalone Node.js service on the LAN. Do not include the
  // Cloudflare runtime plugin here: it emits `cloudflare:` imports that Node
  // cannot execute.
  plugins: [vinext()],
});
