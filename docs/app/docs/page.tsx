import type { Metadata } from "next";

import { DocsSite } from "@/components/docs-site";

export const metadata: Metadata = {
  title: "Guides and reference — Loom Docs",
};

export default function DocumentationPage() {
  return <DocsSite />;
}
