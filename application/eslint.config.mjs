import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import prettier from "eslint-config-prettier/flat";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores([
    "**/node_modules/**",
    "**/dist/**",
    "**/coverage/**",
    "**/.venv/**",
    "packages/contracts/src/generated/**",
  ]),
  {
    files: ["**/*.{js,mjs,cjs,jsx,ts,mts,cts,tsx}"],
    extends: [js.configs.recommended],
  },
  {
    files: ["**/*.{ts,mts,cts,tsx}"],
    extends: [tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["apps/web/src/**/*.{js,jsx,ts,tsx}", "packages/ui/src/**/*.{js,jsx,ts,tsx}"],
    extends: [reactHooks.configs.flat.recommended, jsxA11y.flatConfigs.recommended],
    languageOptions: { globals: globals.browser },
  },
  {
    files: [
      "*.{js,mjs,cjs,ts,mts,cts}",
      "scripts/**/*.{js,mjs,cjs,ts,mts,cts}",
      "apps/web/*.{js,mjs,cjs,ts,mts,cts}",
      "packages/*/*.{js,mjs,cjs,ts,mts,cts}",
    ],
    languageOptions: { globals: globals.node },
  },
  prettier,
]);
