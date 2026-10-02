import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { reconnectCommand, repositoryFiles } from "@/lib/setup-sharing";
import type { Project } from "@/lib/types";

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";

export function SetupSharing({ project }: { project: Project }) {
  return (
    <Stack spacing={2.5} sx={{ maxWidth: 980 }}>
      <Box>
        <Typography
          color="primary.light"
          sx={{ fontFamily: mono, fontSize: 11, textTransform: "uppercase" }}
        >
          {project.name || "Selected project"} / Guide
        </Typography>
        <Typography
          component="h1"
          variant="h1"
          sx={{ fontSize: { xs: 34, sm: 48 }, mt: 1 }}
        >
          Setup &amp; sharing
        </Typography>
        <Typography color="text.secondary" sx={{ lineHeight: 1.7, mt: 1.5 }}>
          Connect this repository on another machine and decide which local
          setup files to share with your team.
        </Typography>
      </Box>

      <Card sx={{ p: { xs: 2.5, sm: 3.5 } }}>
        <Typography component="h2" variant="h2" sx={{ fontSize: 24 }}>
          Use this project on another machine
        </Typography>
        <Typography color="text.secondary" sx={{ lineHeight: 1.7, mt: 1.5 }}>
          From that machine, open the repository, install the Loom CLI, then
          run:
        </Typography>
        <Box
          component="pre"
          sx={{
            bgcolor: "#09090b",
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 1.5,
            color: "#c4b5fd",
            fontFamily: mono,
            fontSize: 13,
            mt: 2,
            overflowX: "auto",
            p: 2,
          }}
        >
          {reconnectCommand(project.id)}
        </Box>
        <Typography color="text.secondary" sx={{ lineHeight: 1.7, mt: 2 }}>
          This signs in and binds the repository to this project. Replace{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            all
          </Box>{" "}
          with{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            codex
          </Box>
          ,{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            claude
          </Box>
          , or{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            opencode
          </Box>{" "}
          to install only the client you use. Review and trust project hooks
          before enabling them in your client.
        </Typography>
      </Card>

      <Card sx={{ p: { xs: 2.5, sm: 3.5 } }}>
        <Typography component="h2" variant="h2" sx={{ fontSize: 24, mb: 2 }}>
          Files Loom creates in the repository
        </Typography>
        <Box
          sx={{
            display: "grid",
            gap: 1.5,
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
          }}
        >
          {repositoryFiles.map((file) => (
            <Box
              key={file.path}
              sx={{
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 1.5,
                minWidth: 0,
                p: 2,
              }}
            >
              <Typography
                component="h3"
                sx={{
                  color: "primary.light",
                  fontFamily: mono,
                  fontSize: 13,
                  overflowWrap: "anywhere",
                }}
              >
                {file.path}
              </Typography>
              <Typography
                color="text.secondary"
                sx={{ fontSize: 13, lineHeight: 1.6, mt: 1 }}
              >
                {file.purpose}
              </Typography>
            </Box>
          ))}
        </Box>
      </Card>

      <Card sx={{ p: { xs: 2.5, sm: 3.5 } }}>
        <Typography component="h2" variant="h2" sx={{ fontSize: 24 }}>
          Git is optional
        </Typography>
        <Typography sx={{ lineHeight: 1.7, mt: 1.5 }}>
          No push is required for Loom to work. Keep generated repository files
          local by default, or deliberately commit non-secret configuration if
          your team wants to share the setup.
        </Typography>
        <Typography color="text.secondary" sx={{ lineHeight: 1.7, mt: 1.5 }}>
          Private credentials and capture data in{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            ~/.loom/
          </Box>{" "}
          must never be committed. Review generated files before committing
          them.
        </Typography>
        <Typography color="text.secondary" sx={{ lineHeight: 1.7, mt: 1.5 }}>
          For day-to-day checks, run{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            loom capture status
          </Box>
          . Run{" "}
          <Box component="code" sx={{ fontFamily: mono }}>
            loom capture pause
          </Box>{" "}
          before entering sensitive text.
        </Typography>
      </Card>
    </Stack>
  );
}
