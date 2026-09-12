"use client";

import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: "#8b5cf6", light: "#a78bfa" },
    background: { default: "#08080a", paper: "#111114" },
    text: { primary: "#f5f3f7", secondary: "#918d99" },
    divider: "rgba(255,255,255,0.1)",
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily:
      "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    h1: { fontWeight: 520, letterSpacing: "-0.055em" },
    h2: { fontWeight: 560, letterSpacing: "-0.035em" },
    button: { textTransform: "none", fontWeight: 650 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        "*:focus-visible": {
          outline: "2px solid #a78bfa",
          outlineOffset: "2px",
        },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": {
            animationDuration: "0.01ms !important",
            animationIterationCount: "1 !important",
            scrollBehavior: "auto !important",
            transitionDuration: "0.01ms !important",
          },
        },
      },
    },
    MuiButtonBase: { defaultProps: { disableRipple: true } },
    MuiButton: { styleOverrides: { root: { minHeight: 42 } } },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid rgba(255,255,255,0.1)",
          boxShadow: "0 24px 70px rgba(0,0,0,0.22)",
        },
      },
    },
  },
});
