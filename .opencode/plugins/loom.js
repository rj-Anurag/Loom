import { spawn } from "node:child_process";

const contextForPrompt = (directory, prompt) => new Promise((resolve) => {
  const child = spawn("loom", ["prompt-hook"], {
    cwd: directory, stdio: ["pipe", "pipe", "ignore"],
  });
  let output = "";
  const timer = setTimeout(() => child.kill(), 4500);
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.on("error", () => { clearTimeout(timer); resolve(""); });
  child.on("close", () => {
    clearTimeout(timer);
    try { resolve(JSON.parse(output).hookSpecificOutput?.additionalContext ?? ""); }
    catch { resolve(""); }
  });
  child.stdin.on("error", () => {});
  child.stdin.end(JSON.stringify({ prompt }));
});

export const LoomCapture = async ({ client, directory }) => {
  const contexts = new Map();
  return {
  "chat.message": async (input, output) => {
    const prompt = output.parts.filter((part) => part.type === "text")
      .map((part) => part.text).join("\n");
    if (!prompt.trim()) return;
    contexts.set(input.sessionID ?? "default", await contextForPrompt(directory, prompt));
  },
  "experimental.chat.system.transform": async (input, output) => {
    const context = contexts.get(input.sessionID ?? "default");
    if (context) output.system.push(context);
  },
  event: async ({ event }) => {
    if (event.type !== "session.idle") return;
    const id = event.properties?.sessionID;
    if (!id) return;
    try {
      const [session, messages] = await Promise.all([
        client.session.get({ path: { id } }),
        client.session.messages({ path: { id } }),
      ]);
      if (session.data?.parentID) return;
      const payload = {
        cwd: directory,
        session_id: id,
        session_title: session.data?.title,
        messages: (messages.data ?? [])
          .filter(({ info }) => info.role === "user" ||
            (info.role === "assistant" && info.finish === "stop"))
          .map(({ info, parts }) => ({
          id: info.id,
          role: info.role,
          finish: info.finish,
          occurred_at: info.time?.created
            ? new Date(info.time.created).toISOString() : undefined,
          parts: parts.filter((part) => part.type === "text")
            .map(({ type, text }) => ({ type, text })),
        })),
      };
      const child = spawn("loom", ["capture", "event", "opencode"], {
        cwd: directory, stdio: ["pipe", "ignore", "ignore"],
      });
      child.on("error", (error) => console.error("Loom capture:", error.message));
      child.stdin.on("error", (error) => console.error("Loom capture:", error.message));
      child.stdin.end(JSON.stringify(payload));
    } catch (error) {
      console.error("Loom capture:", error.message);
    }
  },
  };
};
