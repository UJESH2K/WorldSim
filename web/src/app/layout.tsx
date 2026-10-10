import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Lucid · drone flight simulator in a generated world", template: "%s · Lucid" },
  description:
    "Lucid turns one photo into a photoreal world, lets a drone practise inside it, and calls every near miss and crash before the drone ever flies for real.",
  openGraph: {
    title: "Lucid · teach a drone to fly safely before it leaves the ground",
    description: "A drone flies inside a world generated in real time, and a safety referee calls every crash.",
    images: ["/showcase/hero.jpg"],
  },
};

export const viewport: Viewport = {
  themeColor: "#0b0c0e",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
