"use client";

import { useEffect } from "react";

export function LegacyDocsHashRedirect() {
  useEffect(() => {
    if (window.location.hash) {
      window.location.replace(`/docs${window.location.hash}`);
    }
  }, []);

  return null;
}
