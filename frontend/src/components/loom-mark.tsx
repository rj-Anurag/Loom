"use client";

import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Image from "next/image";
import Link from "next/link";

export function LoomMark({ compact = false }: { compact?: boolean }) {
  return (
    <Link
      aria-label="Loom home"
      href="/"
      style={{ color: "inherit", textDecoration: "none" }}
    >
      <Stack direction="row" alignItems="center" spacing={1.25}>
        <Image
          alt=""
          aria-hidden="true"
          height={38}
          priority
          src="/loom-logo.png"
          width={38}
        />
        {!compact && (
          <Typography
            sx={{ fontSize: 19, fontWeight: 720, letterSpacing: "-0.04em" }}
          >
            Loom
          </Typography>
        )}
      </Stack>
    </Link>
  );
}
