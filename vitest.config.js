import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.js"],
    coverage: {
      provider: "v8",
      include: ["receiver/*.js"],
      exclude: ["tests/**"],
      reporter: [["text", { skipFull: false }]],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 }
    }
  }
});
