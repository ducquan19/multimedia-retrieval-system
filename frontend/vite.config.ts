import { createLogger, defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const REFUSED_NOTICE_INTERVAL_MS = 30_000;

// While the backend is still loading its models every proxied request is refused, and Vite
// prints a stack trace for each one. Collapse those into one short, throttled notice.
function createDevLogger(target: string) {
  const logger = createLogger();
  const logError = logger.error;
  let lastNotice = 0;
  logger.error = (msg, options) => {
    if (msg.includes("http proxy error") && msg.includes("ECONNREFUSED")) {
      const now = Date.now();
      if (now - lastNotice >= REFUSED_NOTICE_INTERVAL_MS) {
        lastNotice = now;
        logger.warn(`Backend at ${target} is not accepting connections yet (still starting?)`, {
          timestamp: true,
        });
      }
      return;
    }
    logError(msg, options);
  };
  return logger;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_DEV_API_TARGET || "http://localhost:8000";

  return {
    customLogger: createDevLogger(apiTarget),
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
        "/media": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      include: ["src/**/*.test.{ts,tsx}"],
      css: true,
    },
  };
});
