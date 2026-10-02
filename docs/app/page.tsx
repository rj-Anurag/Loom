import { DocsHome } from "@/components/docs-home";
import { LegacyDocsHashRedirect } from "@/components/legacy-docs-hash-redirect";

export default function Home() {
  return (
    <>
      <LegacyDocsHashRedirect />
      <DocsHome />
    </>
  );
}
