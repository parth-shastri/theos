import "./globals.css";
import { headers } from "next/headers";

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export default async function RootLayout({ children }) {
  const agentName = process.env.AGENT_NAME || "Theos";
  const nonce = (await headers()).get("x-nonce");
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script src="/static/theme.js" nonce={nonce} />
        <title>{`${agentName} / Personal assistant`}</title>
        <link rel="icon" type="image/png" href="/static/brand-light.png" />
        <link rel="apple-touch-icon" href="/static/brand-light.png" />
      </head>
      <body>
        <div className="app-viewport">{children}</div>
      </body>
    </html>
  );
}
