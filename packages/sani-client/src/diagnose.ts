/**
 * Why a client cannot reach the server.
 *
 * "Cannot reach the server, start it with uvicorn" is the right advice exactly
 * once: when the page and the backend are both local. On a hosted page it is
 * actively misleading -- the user starts a local server, nothing changes, and
 * the message still says the same thing. These are the cases worth telling
 * apart, and they are pure functions so they can be tested rather than
 * eyeballed in a browser.
 */

const LOOPBACK_HOSTS = ["localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"];

export type ConnectionProblem =
  | "unauthorized"
  | "loopback-from-hosted"
  | "insecure-mix"
  | "unreachable";

export interface DiagnoseInput {
  /** The configured backend base URL. */
  server: string;
  /** Where the client itself is running, e.g. window.location.href. */
  pageUrl: string;
  /** HTTP status of the failed request, when there was one. */
  status?: number | null;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

export function isLoopback(host: string): boolean {
  return LOOPBACK_HOSTS.includes(host);
}

/** A page not served from the machine the user is sitting at. */
export function isHostedPage(pageUrl: string): boolean {
  const host = hostOf(pageUrl);
  return host !== "" && !isLoopback(host);
}

/** HTTPS page, plaintext backend: the browser refuses before we ever connect. */
export function isInsecureMix(server: string, pageUrl: string): boolean {
  return pageUrl.startsWith("https://") && server.startsWith("http://");
}

export function diagnoseConnection({
  server,
  pageUrl,
  status,
}: DiagnoseInput): ConnectionProblem {
  if (status === 401 || status === 403) return "unauthorized";

  // Checked before the mixed-content case because it is the more specific and
  // more common mistake: a hosted build still carrying its default localhost.
  if (isHostedPage(pageUrl) && isLoopback(hostOf(server))) {
    return "loopback-from-hosted";
  }
  if (isInsecureMix(server, pageUrl)) return "insecure-mix";
  return "unreachable";
}

export function explainProblem(problem: ConnectionProblem, server: string): string {
  switch (problem) {
    case "unauthorized":
      return `${server} rejected this request: it requires an auth token and this browser has none, or the wrong one.`;
    case "loopback-from-hosted":
      return `This page is hosted, but it is calling ${server} — in your browser that means your own machine, not a server. Expose the backend over an HTTPS tunnel and point at that URL.`;
    case "insecure-mix":
      return `This page is HTTPS and ${server} is plain HTTP, so the browser blocks the request. Use an https:// URL.`;
    case "unreachable":
      return `Cannot reach ${server}.`;
  }
}

/**
 * Catch the two fields being filled with each other's value.
 *
 * The connection panel asks for a server URL and a bearer token one after the
 * other, and both arrive via the clipboard, so crossing them is easy and the
 * consequence is opaque: a URL in the token field produces an endless stream of
 * 401s that look identical to a stale token, and no amount of correcting the
 * *server* field fixes it. Worth naming at the point of entry rather than
 * leaving someone to infer it from a log.
 *
 * Deliberately advisory. It returns a warning, never blocks a save — a token
 * format is the server operator's business, and refusing an unusual one would be
 * a worse failure than a hint.
 */
export function credentialWarning(input: { server: string; token: string }): string | null {
  const token = input.token.trim();
  const server = input.server.trim();

  if (token && /^[a-z][a-z0-9+.-]*:\/\//i.test(token)) {
    return "That looks like a URL, not a token — it belongs in the Server URL field above.";
  }
  // Whitespace is the tell for "the clipboard had something else". Bearer tokens
  // never contain it, and the something else is usually a shell command copied
  // out of a terminal or a chat a moment earlier -- which is not a URL and not a
  // provider key, so nothing else here would catch it.
  if (/\s/.test(token)) {
    return "That contains spaces or line breaks, so it is not a token — it looks like a copied command or a wrapped line. Check what was on your clipboard.";
  }
  // A Groq/OpenAI-style key is for the *server* to hold when it calls the model;
  // sending it here would hand your model credentials to the wrong party.
  if (/^(gsk_|sk-)/.test(token)) {
    return "That looks like a model provider API key. It belongs in the server's environment, not in this browser — the auth token is the one the server prints on startup.";
  }
  if (server && !/[./:]/.test(server) && server.length > 24) {
    return "The Server URL looks like a token. It should be a host, e.g. https://something.trycloudflare.com.";
  }
  return null;
}
