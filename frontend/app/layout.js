import "./globals.css";

export const metadata = {
  title: "ApexSim AI – F1 Telemetry Analysis",
  description:
    "Compare Formula 1 driver telemetry side-by-side in stunning 3D with live AI coaching powered by IBM Granite and FastF1.",
  icons: {
    icon: "/logo.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
