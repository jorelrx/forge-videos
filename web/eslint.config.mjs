import { type Linter } from "eslint";
import next from "eslint-config-next";

const config: Linter.Config[] = [
  ...next,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": "warn",
    },
  },
];

export default config;
