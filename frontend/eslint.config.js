// ESLint flat config (platform-foundation RF-19): typescript-eslint type-checked + react-hooks.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "src/lib/api/generated/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    // D-22 / tuning RF-12: three.js só em chunk lazy (Table3DView), nunca no bundle inicial.
    files: ["src/**/*.{ts,tsx}"],
    ignores: [
      "src/features/ecu-tuning/**/Table3D*.{ts,tsx}",
      "src/features/ecu-tuning/three/**",
      "src/**/*.test.{ts,tsx}",
    ],
    rules: {
      "@typescript-eslint/no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "three",
              message: "three.js só em features/ecu-tuning/Table3D* (chunk lazy, D-22).",
              allowTypeImports: true,
            },
          ],
          patterns: [
            {
              group: ["three/*"],
              message: "three.js só em features/ecu-tuning/Table3D* (chunk lazy, D-22).",
              allowTypeImports: true,
            },
          ],
        },
      ],
    },
  },
  {
    files: ["**/*.js"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: { globals: { ...globals.node } },
  },
);
