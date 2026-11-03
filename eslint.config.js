import js from "@eslint/js";
import globals from "globals";

// The receiver is plain browser scripts loaded one after another by index.html, so
// each one reaches the earlier ones, and the libraries, through globals.
const receiverGlobals = {
  ...globals.browser,
  cast: "readonly",
  maplibregl: "readonly",
  pmtiles: "readonly",
  basemaps: "readonly",
  FlightMap: "readonly",
  RouteMap: "readonly",
  FollowedCard: "readonly",
  Speaker: "readonly",
  RightAway: "readonly",
  WhenHubUnmuted: "readonly"
};

export default [
  { ignores: ["receiver/vendor/", "node_modules/", "coverage/", "**/.venv/"] },
  js.configs.recommended,
  {
    rules: {
      "no-unused-vars": ["error", { args: "after-used", argsIgnorePattern: "^_", caughtErrors: "none" }],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "prefer-const": "error"
    }
  },
  { files: ["receiver/*.js"], languageOptions: { sourceType: "script", globals: receiverGlobals } },
  { files: ["tests/**/*.js", "*.config.js"], languageOptions: { globals: { ...globals.node, ...globals.browser } } }
];
