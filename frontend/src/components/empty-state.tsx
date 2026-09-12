"use client";

import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: string;
}) {
  return (
    <Box sx={{ color: "text.secondary", py: 5, textAlign: "center" }}>
      <Typography
        aria-hidden="true"
        sx={{ color: "primary.light", fontSize: 34 }}
      >
        ⌁
      </Typography>
      <Typography
        component="h2"
        sx={{ color: "text.primary", fontSize: 18, fontWeight: 620 }}
      >
        {title}
      </Typography>
      <Typography sx={{ fontSize: 13, mt: 0.75 }}>{children}</Typography>
    </Box>
  );
}
