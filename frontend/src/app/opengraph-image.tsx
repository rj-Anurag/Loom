import { ImageResponse } from "next/og";

export const alt = "Loom — One project. Every agent. Shared context.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        alignItems: "center",
        backgroundColor: "#08080a",
        backgroundImage:
          "linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px), radial-gradient(circle at 50% 52%, rgba(139,92,246,.28), transparent 46%)",
        backgroundSize: "40px 40px, 40px 40px, 100% 100%",
        color: "#f5f3f7",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        justifyContent: "center",
        padding: "76px",
        width: "100%",
      }}
    >
      <div
        style={{
          alignItems: "center",
          display: "flex",
          fontSize: 34,
          fontWeight: 700,
          gap: 16,
          left: 76,
          position: "absolute",
          top: 58,
        }}
      >
        <div
          style={{
            alignItems: "center",
            background: "#8b5cf6",
            borderRadius: 12,
            display: "flex",
            fontSize: 27,
            height: 48,
            justifyContent: "center",
            width: 48,
          }}
        >
          L
        </div>
        Loom
      </div>
      <div
        style={{
          display: "flex",
          fontSize: 79,
          fontWeight: 700,
          letterSpacing: "-4px",
          lineHeight: 1.02,
          maxWidth: 1030,
          textAlign: "center",
        }}
      >
        One project. Every agent.
      </div>
      <div
        style={{
          color: "#a78bfa",
          display: "flex",
          fontSize: 79,
          fontWeight: 700,
          letterSpacing: "-4px",
          lineHeight: 1.02,
          textAlign: "center",
        }}
      >
        Shared context.
      </div>
      <div
        style={{
          color: "#918d99",
          display: "flex",
          fontSize: 24,
          marginTop: 36,
        }}
      >
        Browser conversations → project memory → coding agents
      </div>
      <div
        style={{
          bottom: 54,
          color: "#a78bfa",
          display: "flex",
          fontFamily: "monospace",
          fontSize: 16,
          letterSpacing: 3,
          position: "absolute",
          right: 76,
          textTransform: "uppercase",
        }}
      >
        loom / shared agent context
      </div>
    </div>,
    size,
  );
}
