import type React from "react";
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Suspense } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as SonnerToaster } from "sonner";
import Link from "next/link";

export const metadata: Metadata = {
  title: "v0 App",
  description: "Created with v0",
  generator: "v0.app",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme');
                  if (theme === 'dark') {
                    document.documentElement.classList.add('dark');
                  } else {
                    document.documentElement.classList.remove('dark');
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <Suspense fallback={<div>Loading...</div>}>
          <ThemeProvider defaultTheme="light" storageKey="theme">
            {/* Convergence Feed is a research instrument, not part of the chat product.
                Its background loop is off by default (CONVERGENCE_LOOP_ENABLED in
                api_server.py), so this link would lead to a page whose data no longer
                updates. The route itself still exists for internal use. */}
            <div className="fixed top-2 right-3 z-50 flex items-center gap-3 rounded-full border bg-background/90 px-3 py-1.5 shadow-sm backdrop-blur">
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground">
                Chat
              </Link>
              <Link href="/ml" className="text-xs font-medium text-foreground">
                H2O ML Studio
              </Link>
              {process.env.NEXT_PUBLIC_SHOW_CONVERGENCE === "1" && (
                <Link href="/convergence" className="text-xs text-muted-foreground underline">
                  Convergence Feed
                </Link>
              )}
            </div>
            {children}
            <Toaster />
            <SonnerToaster richColors closeButton position="bottom-right" />
          </ThemeProvider>
        </Suspense>
        <Analytics />
      </body>
    </html>
  );
}
