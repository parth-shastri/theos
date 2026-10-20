import "./globals.css";

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export default function RootLayout({ children }) {
  const agentName = process.env.AGENT_NAME || "Theos";
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <title>{agentName} / Personal assistant</title>
        <link rel="icon" type="image/png" href="/static/brand-light.png" />
        <link rel="apple-touch-icon" href="/static/brand-light.png" />
      </head>
      <body>{children}</body>
    </html>
  );
}
