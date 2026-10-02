"use client";

import Alert from "@mui/material/Alert";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import { Menu as MenuIcon } from "lucide-react";
import Script from "next/script";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { LoomMark } from "@/components/loom-mark";
import { SetupSharing } from "@/components/setup-sharing";
import { SourceExplorer, SourceNavigation } from "@/components/source-explorer";
import { apiRequest, formatDate, friendlyError, initials } from "@/lib/api";
import { ALL_SOURCES_ID, buildMemorySources } from "@/lib/sources";
import { isSetupSharingSelected } from "@/lib/setup-sharing";
import type {
  AuthPayload,
  Chat,
  ContextUnit,
  HistoryPage,
  Project,
  User,
} from "@/lib/types";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: {
            client_id: string;
            callback: (result: { credential: string }) => void;
            auto_select?: boolean;
            button_auto_select?: boolean;
            use_fedcm_for_button?: boolean;
          }): void;
          renderButton(
            element: HTMLElement,
            options: Record<string, string | number>,
          ): void;
          disableAutoSelect(): void;
        };
      };
    };
  }
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
let initializedGoogleClientId = "";
let googleCredentialHandler: ((credential: string) => void) | null = null;

function GoogleButton({
  error,
  initialized,
}: {
  error: string;
  initialized: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    const root = rootRef.current;
    if (!initialized || !root || !window.google) return;
    let cancelled = false;
    root.replaceChildren();
    window.google.accounts.id.renderButton(root, {
      logo_alignment: "left",
      shape: "rectangular",
      text: "signin_with",
      theme: "filled_black",
      type: "standard",
      size: "large",
      width: 320,
    });
    queueMicrotask(() => {
      if (!cancelled) setRendered(true);
    });
    return () => {
      cancelled = true;
      root.replaceChildren();
    };
  }, [initialized]);

  return (
    <Box sx={{ height: 44, mt: 3, position: "relative", width: 320 }}>
      {!error && !rendered && (
        <Button
          disabled
          startIcon={<CircularProgress size={16} />}
          sx={{ height: 40, left: 0, position: "absolute", top: 0, width: 320 }}
          variant="outlined"
        >
          Loading Google sign-in…
        </Button>
      )}
      <Box ref={rootRef} sx={{ position: "relative", zIndex: 1 }} />
    </Box>
  );
}

function AuthView({
  authError,
  googleError,
  googleInitialized,
}: {
  authError: string;
  googleError: string;
  googleInitialized: boolean;
}) {
  return (
    <Box
      component="main"
      sx={{ minHeight: "100vh", overflow: "hidden", px: { xs: 2, sm: 4 } }}
    >
      <Box sx={{ maxWidth: 1180, mx: "auto" }}>
        <Stack
          component="nav"
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          sx={{ py: 2.5 }}
        >
          <LoomMark />
          <Typography
            sx={{
              color: "text.secondary",
              fontFamily: mono,
              fontSize: 10,
              letterSpacing: ".08em",
              textTransform: "uppercase",
            }}
          >
            Context network online
          </Typography>
        </Stack>

        <Box sx={{ pb: 7, pt: { xs: 8, md: 13 } }}>
          <Typography
            sx={{
              color: "primary.light",
              fontFamily: mono,
              fontSize: 11,
              letterSpacing: ".13em",
              textTransform: "uppercase",
            }}
          >
            Project memory / for every agent
          </Typography>
          <Typography
            component="h1"
            variant="h1"
            sx={{
              fontSize: { xs: 54, sm: 76, md: 104 },
              lineHeight: 0.92,
              mt: 2.5,
              maxWidth: 940,
            }}
          >
            Context that{" "}
            <Box component="span" sx={{ color: "primary.main" }}>
              moves with you.
            </Box>
          </Typography>
          <Typography
            sx={{
              color: "text.secondary",
              fontSize: { xs: 16, md: 18 },
              lineHeight: 1.7,
              maxWidth: 590,
              ml: { md: "auto" },
              mt: 4,
            }}
          >
            Bring browser conversations and terminal agents into one persistent
            project memory. Start once, continue anywhere.
          </Typography>
        </Box>

        <Box
          sx={{
            display: "grid",
            gap: 2,
            gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          }}
        >
          <Card sx={{ p: { xs: 3, md: 4 } }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 10,
                mb: 6,
                textTransform: "uppercase",
              }}
            >
              <span>01 / Account</span>
              <span>Google identity</span>
            </Stack>
            <Typography component="h2" variant="h2" sx={{ fontSize: 30 }}>
              Continue to Loom
            </Typography>
            <Typography
              color="text.secondary"
              sx={{ lineHeight: 1.7, mt: 1.5 }}
            >
              One Google identity connects your dashboard, CLI, and browser
              extension.
            </Typography>
            <GoogleButton error={googleError} initialized={googleInitialized} />
            {(authError || googleError) && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {authError || googleError}
              </Alert>
            )}
          </Card>

          <Card sx={{ p: { xs: 3, md: 4 } }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              sx={{
                color: "text.secondary",
                fontFamily: mono,
                fontSize: 10,
                mb: 6,
                textTransform: "uppercase",
              }}
            >
              <span>02 / Connect</span>
              <span>3 steps</span>
            </Stack>
            <Typography
              component="h2"
              variant="h2"
              sx={{ fontSize: 30, mb: 3 }}
            >
              Connect in minutes
            </Typography>
            {[
              [
                "1",
                "Install the CLI.",
                "curl -fsSL https://raw.githubusercontent.com/rj-Anurag/Loom/main/install.sh | bash",
              ],
              [
                "2",
                "Connect this repository.",
                'loom login\nloom init "My Project"',
              ],
              ["3", "Install the bundled extension.", "loom extension install"],
            ].map(([number, label, command]) => (
              <Stack key={number} direction="row" spacing={2} sx={{ mb: 2.5 }}>
                <Avatar
                  sx={{
                    bgcolor: "primary.main",
                    color: "white",
                    height: 28,
                    fontSize: 12,
                    width: 28,
                  }}
                >
                  {number}
                </Avatar>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography sx={{ fontSize: 14 }}>{label}</Typography>
                  <Box
                    component="pre"
                    sx={{
                      bgcolor: "#09090b",
                      border: "1px solid",
                      borderColor: "divider",
                      borderRadius: 1.5,
                      color: "#c4b5fd",
                      fontFamily: mono,
                      fontSize: 11,
                      mt: 1,
                      overflowX: "auto",
                      p: 1.5,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {command}
                  </Box>
                </Box>
              </Stack>
            ))}
          </Card>
        </Box>
        <Stack
          component="footer"
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          sx={{
            color: "text.secondary",
            fontFamily: mono,
            fontSize: 9,
            gap: 1,
            py: 4,
            textTransform: "uppercase",
          }}
        >
          <span>Loom / Shared agent context</span>
          <span>Browser → Project memory → Terminal</span>
        </Stack>
      </Box>
    </Box>
  );
}

function AccountAppContent({
  googleReady,
  googleScriptError,
}: {
  googleReady: boolean;
  googleScriptError: string;
}) {
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up("md"));
  const [booting, setBooting] = useState(true);
  const [revealSignIn, setRevealSignIn] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [units, setUnits] = useState<ContextUnit[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState(ALL_SOURCES_ID);
  const [loadingProject, setLoadingProject] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [authError, setAuthError] = useState("");
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleConfigError, setGoogleConfigError] = useState("");
  const [googleInitialized, setGoogleInitialized] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [profileAnchor, setProfileAnchor] = useState<HTMLElement | null>(null);
  const loadVersion = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function loadGoogleConfig() {
      try {
        const config = await apiRequest<{
          enabled: boolean;
          client_id: string;
        }>("/v1/auth/google/config?client_kind=web");
        if (!config.enabled || !config.client_id)
          throw new Error("GOOGLE_AUTH_NOT_CONFIGURED");
        if (!cancelled) setGoogleClientId(config.client_id);
      } catch (error) {
        if (!cancelled)
          setGoogleConfigError(
            friendlyError(
              error instanceof Error ? error.message : "Request failed",
            ),
          );
      }
    }
    void loadGoogleConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadHistory = useCallback(
    async (projectId: string, version: number) => {
      const collected: ContextUnit[] = [];
      let cursor = "";
      do {
        const suffix = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
        const page = await apiRequest<HistoryPage>(
          `/v1/projects/${projectId}/history?limit=200${suffix}`,
        );
        if (version !== loadVersion.current) return [];
        collected.push(...(page.units ?? []));
        cursor = page.has_more ? (page.next_cursor ?? "") : "";
      } while (cursor);
      return collected;
    },
    [],
  );

  const selectProject = useCallback(
    async (selected: Project) => {
      const version = ++loadVersion.current;
      setProject(selected);
      setSelectedSourceId(ALL_SOURCES_ID);
      setChats([]);
      setUnits([]);
      setProjectError("");
      setLoadingProject(true);
      try {
        const [details, projectChats, history] = await Promise.all([
          apiRequest<Project>(`/v1/projects/${selected.id}`),
          apiRequest<Chat[]>(`/v1/projects/${selected.id}/chats`),
          loadHistory(selected.id, version),
        ]);
        if (version !== loadVersion.current) return;
        setProject({ ...selected, ...details });
        setChats(projectChats ?? []);
        setUnits(history);
      } catch (error) {
        if (version === loadVersion.current) {
          setProjectError(
            friendlyError(
              error instanceof Error ? error.message : "Request failed",
            ),
          );
        }
      } finally {
        if (version === loadVersion.current) setLoadingProject(false);
      }
    },
    [loadHistory],
  );

  const applySession = useCallback(
    (payload: AuthPayload) => {
      const nextUser = payload.user ?? payload;
      const nextProjects = (payload.projects ?? []).filter(Boolean);
      setUser(nextUser);
      setProjects(nextProjects);
      if (nextProjects[0]) void selectProject(nextProjects[0]);
    },
    [selectProject],
  );

  const authenticate = useCallback(
    async (credential: string) => {
      setAuthError("");
      try {
        const payload = await apiRequest<AuthPayload>(
          "/v1/auth/google/exchange",
          {
            method: "POST",
            body: JSON.stringify({ client_kind: "web", id_token: credential }),
          },
        );
        applySession(payload);
      } catch (error) {
        setAuthError(
          friendlyError(
            error instanceof Error ? error.message : "Request failed",
          ),
        );
      }
    },
    [applySession],
  );

  useEffect(() => {
    googleCredentialHandler = authenticate;
    return () => {
      if (googleCredentialHandler === authenticate)
        googleCredentialHandler = null;
    };
  }, [authenticate]);

  useEffect(() => {
    if (!googleReady || !googleClientId || !window.google) return;
    if (initializedGoogleClientId !== googleClientId) {
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: ({ credential }) =>
          void googleCredentialHandler?.(credential),
        auto_select: false,
        button_auto_select: false,
        use_fedcm_for_button: true,
      });
      initializedGoogleClientId = googleClientId;
    }

    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setGoogleInitialized(true);
    });
    return () => {
      cancelled = true;
    };
  }, [googleClientId, googleReady]);

  useEffect(() => {
    let cancelled = false;
    const revealTimer = window.setTimeout(() => setRevealSignIn(true), 150);

    async function boot() {
      const params = new URLSearchParams(window.location.hash.slice(1));
      const token = params.get("handoff");
      try {
        if (token) {
          window.history.replaceState(
            null,
            "",
            window.location.pathname + window.location.search,
          );
          await apiRequest<void>("/v1/auth/dashboard-session/consume", {
            method: "POST",
            body: JSON.stringify({ token }),
          });
        }
        const session = await apiRequest<AuthPayload>("/v1/auth/me");
        if (!cancelled) applySession(session);
      } catch {
        if (token && !cancelled)
          setAuthError(
            "Your dashboard link expired. Open the dashboard from the Loom extension again.",
          );
      } finally {
        window.clearTimeout(revealTimer);
        if (!cancelled) setBooting(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
      window.clearTimeout(revealTimer);
    };
  }, [applySession]);

  const sources = useMemo(
    () => buildMemorySources(chats, units),
    [chats, units],
  );

  if (booting && !revealSignIn) {
    return (
      <Stack
        alignItems="center"
        justifyContent="center"
        sx={{ minHeight: "100vh" }}
      >
        <CircularProgress aria-label="Loading Loom" />
      </Stack>
    );
  }
  if (!user)
    return (
      <AuthView
        authError={authError}
        googleError={googleScriptError || googleConfigError}
        googleInitialized={googleInitialized}
      />
    );

  const closeDrawer = () => setDrawerOpen(false);
  const sidebar = (
    <Box
      component="aside"
      aria-label="Projects and memory sources"
      sx={{
        bgcolor: "#0d0d10",
        height: "100%",
        overflowY: "auto",
        p: 2.5,
        width: 300,
      }}
    >
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="end"
        sx={{ mb: 1.5 }}
      >
        <Box>
          <Typography
            sx={{
              color: "primary.light",
              fontFamily: mono,
              fontSize: 9,
              textTransform: "uppercase",
            }}
          >
            Workspace
          </Typography>
          <Typography component="h2" sx={{ fontSize: 18, fontWeight: 620 }}>
            Your projects
          </Typography>
        </Box>
        <Typography
          sx={{ color: "text.secondary", fontFamily: mono, fontSize: 11 }}
        >
          {projects.length}
        </Typography>
      </Stack>
      {projects.length === 0 ? (
        <EmptyState title="No projects yet">
          Run loom init in a repository to create your first project.
        </EmptyState>
      ) : (
        projects.map((item) => (
          <Button
            key={item.id}
            fullWidth
            aria-pressed={project?.id === item.id}
            onClick={() => {
              void selectProject(item);
              closeDrawer();
            }}
            sx={{
              bgcolor:
                project?.id === item.id
                  ? "rgba(139,92,246,.13)"
                  : "transparent",
              color: "text.primary",
              justifyContent: "flex-start",
              mb: 0.5,
              px: 1.25,
              py: 1,
            }}
          >
            <Avatar
              sx={{
                bgcolor: project?.id === item.id ? "primary.main" : "#242429",
                fontSize: 12,
                height: 30,
                mr: 1.25,
                width: 30,
              }}
            >
              {initials(item.name).slice(0, 1)}
            </Avatar>
            <Box sx={{ minWidth: 0, textAlign: "left" }}>
              <Typography noWrap sx={{ fontSize: 13, fontWeight: 650 }}>
                {item.name || "Untitled project"}
              </Typography>
              <Typography
                noWrap
                sx={{ color: "text.secondary", fontFamily: mono, fontSize: 9 }}
              >
                {item.role || "member"} · {formatDate(item.created_at, true)}
              </Typography>
            </Box>
          </Button>
        ))
      )}
      <Divider sx={{ my: 2.5 }} />
      <SourceNavigation
        project={project}
        sources={sources}
        selectedSourceId={selectedSourceId}
        onSelect={(sourceId) => {
          setSelectedSourceId(sourceId);
          closeDrawer();
        }}
      />
    </Box>
  );

  return (
    <Box sx={{ minHeight: "100vh" }}>
      <Stack
        component="header"
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{
          bgcolor: "rgba(8,8,10,.92)",
          borderBottom: "1px solid",
          borderColor: "divider",
          height: 72,
          px: { xs: 2, md: 3 },
          position: "sticky",
          top: 0,
          zIndex: 30,
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5}>
          {!desktop ? (
            <Button
              aria-label="Open project navigation"
              onClick={() => setDrawerOpen(true)}
              sx={{ minWidth: 44, p: 0.5 }}
            >
              <MenuIcon size={24} />
            </Button>
          ) : null}
          <LoomMark compact={!desktop} />
          {desktop && (
            <Typography color="text.secondary">/ Workspace</Typography>
          )}
        </Stack>
        <Button
          id="profile-button"
          aria-haspopup="menu"
          aria-expanded={Boolean(profileAnchor)}
          onClick={(event) => setProfileAnchor(event.currentTarget)}
          sx={{ color: "text.primary", gap: 1.25 }}
        >
          <Avatar
            src={user.avatar_url}
            alt=""
            sx={{ bgcolor: "primary.main", height: 34, width: 34 }}
          >
            {initials(user.display_name)}
          </Avatar>
          {desktop && (
            <Box sx={{ textAlign: "left" }}>
              <Typography sx={{ fontSize: 12, fontWeight: 700 }}>
                {user.display_name || "Loom user"}
              </Typography>
              <Typography sx={{ color: "text.secondary", fontSize: 10 }}>
                {user.email}
              </Typography>
            </Box>
          )}
        </Button>
        <Menu
          anchorEl={profileAnchor}
          open={Boolean(profileAnchor)}
          onClose={() => setProfileAnchor(null)}
        >
          <MenuItem
            className="g_id_signout"
            onClick={async () => {
              try {
                await apiRequest<void>("/v1/auth/logout", { method: "POST" });
                setAuthError("");
              } catch (error) {
                setAuthError(
                  friendlyError(
                    error instanceof Error ? error.message : "Request failed",
                  ),
                );
              } finally {
                window.google?.accounts.id.disableAutoSelect();
                loadVersion.current += 1;
                setProfileAnchor(null);
                setUser(null);
                setProjects([]);
                setProject(null);
                setChats([]);
                setUnits([]);
                setSelectedSourceId(ALL_SOURCES_ID);
              }
            }}
          >
            Log out
          </MenuItem>
        </Menu>
      </Stack>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "300px minmax(0,1fr)" },
          minHeight: "calc(100vh - 72px)",
        }}
      >
        {desktop ? (
          sidebar
        ) : (
          <Drawer open={drawerOpen} onClose={closeDrawer}>
            {sidebar}
          </Drawer>
        )}
        <Box component="main" sx={{ minWidth: 0, p: { xs: 2, sm: 4, lg: 5 } }}>
          {project && isSetupSharingSelected(selectedSourceId) ? (
            <SetupSharing project={project} />
          ) : (
            <SourceExplorer
              project={project}
              sources={sources}
              selectedSourceId={selectedSourceId}
              units={units}
              loading={loadingProject}
              error={projectError}
            />
          )}
        </Box>
      </Box>
    </Box>
  );
}

export function AccountApp() {
  const [googleReady, setGoogleReady] = useState(false);
  const [googleScriptError, setGoogleScriptError] = useState("");

  return (
    <>
      <Script
        id="google-identity-services"
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onReady={() => {
          setGoogleScriptError("");
          setGoogleReady(true);
        }}
        onError={() =>
          setGoogleScriptError("Google sign-in could not be loaded.")
        }
      />
      <AccountAppContent
        googleReady={googleReady}
        googleScriptError={googleScriptError}
      />
    </>
  );
}
