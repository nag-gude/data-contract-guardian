import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        dcg: {
          surface: "#f8f9ff",
          "surface-container-low": "#eff4ff",
          "surface-container-lowest": "#ffffff",
          "surface-container": "#e5eeff",
          "surface-container-high": "#dce9ff",
          "surface-variant": "#d3e4fe",
          "on-surface": "#0b1c30",
          "on-surface-variant": "#45464d",
          outline: "#76777d",
          "outline-variant": "#c6c6cd",
          primary: "#000000",
          "on-primary": "#ffffff",
          "primary-container": "#131b2e",
          "on-primary-container": "#7c839b",
          secondary: "#006398",
          "on-secondary": "#ffffff",
          "secondary-container": "#5bb8fe",
          "on-secondary-container": "#00476e",
          "tertiary-container": "#002113",
          "on-tertiary-container": "#009668",
          error: "#ba1a1a",
          "on-error-container": "#93000a",
          "error-container": "#ffdad6",
          "inverse-on-surface": "#eaf1ff",
        },
        ink: { 950: "#0a0f1a", 900: "#0f172a", 800: "#1e293b" },
        accent: { DEFAULT: "#006398", dim: "#00476e" },
        danger: "#ba1a1a",
        ok: "#009668",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
