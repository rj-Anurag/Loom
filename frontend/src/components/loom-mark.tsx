"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

export function LoomMark({ compact = false }: { compact?: boolean }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1.25}>
      <Box
        aria-hidden="true"
        sx={{
          alignItems: "flex-end",
          bgcolor: "#17171b",
          border: "1px solid",
          borderColor: "divider",
          borderRadius: 2.25,
          display: "flex",
          gap: "3px",
          height: 38,
          justifyContent: "center",
          p: "8px",
          width: 38,
        }}
      >
        {[10, 21, 15].map((height) => (
          <Box
            key={height}
            sx={{
              bgcolor: "primary.main",
              borderRadius: 4,
              height,
              width: 5,
            }}
          />
        ))}
      </Box>
      {!compact && (
        <Typography
          sx={{ fontSize: 19, fontWeight: 720, letterSpacing: "-0.04em" }}
        >
          Loom
        </Typography>
      )}
    </Stack>
  );
}
