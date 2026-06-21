/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "#F6F7F9", subtle: "#EEF0F4", card: "#FFFFFF", elevated: "#F1F3F6" },
        border: { DEFAULT: "#E5E7EB", subtle: "#F1F3F6" },
        fg: { DEFAULT: "#0B0F19", muted: "#475569", subtle: "#94A3B8" },
        accent: { DEFAULT: "#0EA5E9", hover: "#0284C7" },
        secondary: { DEFAULT: "#06B6D4" },
        success: "#10B981",
        danger: "#EF4444",
        warning: "#F59E0B",
      },
      fontFamily: {
        sans: ["Geist", "Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(16,24,40,.04), 0 8px 24px -16px rgba(16,24,40,.25)",
        cta: "0 10px 24px -10px rgba(11,15,25,.55)",
      },
      borderRadius: { xl2: "1.25rem" },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-in": "fade-in .4s ease both",
        "fade-up": "fade-up .5s cubic-bezier(.2,.7,.2,1) both",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
