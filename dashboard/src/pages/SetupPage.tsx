import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getApiBase } from "../apiBase";

type SetupStatus = {
  client_configured: boolean;
  refresh_token_configured: boolean;
  mood_mapping_saved: boolean;
  oauth_authorize_path: string;
  oauth_redirect_uri: string;
};

type PlaylistOption = { uri: string; name: string };

type SuggestionsPayload = {
  suggestions: Record<string, { uri: string; name: string; score: number } | null>;
  candidates: PlaylistOption[];
};

const moods = ["calm", "focus", "hype"] as const;

function splitUriList(input: string): string[] {
  return input
    .replace(/\r\n/g, "\n")
    .replace(/,/g, "\n")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function SetupPage() {
  const api = useMemo(() => getApiBase(), []);
  const [searchParams, setSearchParams] = useSearchParams();

  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [candidates, setCandidates] = useState<PlaylistOption[]>([]);
  const [suggestions, setSuggestions] =
    useState<SuggestionsPayload["suggestions"] | null>(null);
  const [calmSelect, setCalmSelect] = useState("");
  const [focusSelect, setFocusSelect] = useState("");
  const [hypeSelect, setHypeSelect] = useState("");
  const [deepSelect, setDeepSelect] = useState("");
  const [calmOverride, setCalmOverride] = useState("");
  const [focusOverride, setFocusOverride] = useState("");
  const [hypeOverride, setHypeOverride] = useState("");
  const [deepOverride, setDeepOverride] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);

  const connectedBanner = searchParams.get("spotify") === "connected";

  const clearConnectedParam = useCallback(() => {
    searchParams.delete("spotify");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const loadStatus = useCallback(() => {
    fetch(`${api}/spotify/setup/status`)
      .then((r) => r.json())
      .then((j: SetupStatus) => setStatus(j))
      .catch(() => setStatus(null));
  }, [api]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const loadSuggestions = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${api}/spotify/playlists/suggestions`)
      .then(async (r) => {
        if (!r.ok) {
          const t = await r.text();
          throw new Error(t || r.statusText);
        }
        return r.json() as Promise<SuggestionsPayload>;
      })
      .then((data) => {
        setCandidates(
          [...data.candidates].sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
          ),
        );
        setSuggestions(data.suggestions);
        setLastSyncedAt(new Date().toLocaleTimeString());
        setMessage(null);
      })
      .catch((e: Error) => {
        setError(e.message || "Could not load playlists");
        setCandidates([]);
        setSuggestions(null);
      })
      .finally(() => setLoading(false));
  }, [api]);

  useEffect(() => {
    if (status?.refresh_token_configured) {
      loadSuggestions();
    }
  }, [status?.refresh_token_configured, loadSuggestions]);

  const applySuggestions = () => {
    if (!suggestions) return;
    setCalmOverride("");
    setFocusOverride("");
    setHypeOverride("");
    for (const m of moods) {
      const s = suggestions[m];
      if (!s) continue;
      if (m === "calm") setCalmSelect(s.uri);
      if (m === "focus") setFocusSelect(s.uri);
      if (m === "hype") setHypeSelect(s.uri);
    }
    setMessage("Applied keyword-based suggestions — adjust if needed, then Save.");
  };

  const saveMapping = () => {
    setError(null);
    setMessage(null);
    const calm = [...(calmSelect ? [calmSelect] : []), ...splitUriList(calmOverride)];
    const focus = [...(focusSelect ? [focusSelect] : []), ...splitUriList(focusOverride)];
    const hype = [...(hypeSelect ? [hypeSelect] : []), ...splitUriList(hypeOverride)];
    const deep = [...(deepSelect ? [deepSelect] : []), ...splitUriList(deepOverride)];
    const body: Record<string, string[] | null> = {
      calm_uri: calm,
      focus_uri: focus,
      hype_uri: hype,
      deep_focus_uri: deep.length ? deep : null,
    };
    fetch(`${api}/spotify/playlists/mapping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) {
          let detail = r.statusText;
          try {
            const j = await r.json();
            if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
          } catch {
            /* ignore */
          }
          throw new Error(detail);
        }
        return r.json();
      })
      .then(
        (data: {
          bootstrap_playback_ok?: boolean;
          bootstrap_playback_error?: string | null;
        }) => {
          if (data.bootstrap_playback_ok) {
            setMessage("Saved. Playback started on your calm playlist.");
          } else if (data.bootstrap_playback_error) {
            setMessage(
              `Saved mapping. Playback: ${data.bootstrap_playback_error}`,
            );
          } else {
            setMessage("Saved mood → playlist mapping.");
          }
          loadStatus();
        },
      )
      .catch((e: Error) => setError(e.message));
  };

  const connectHref = `${api}/spotify/oauth/authorize`;

  const selectClass = "setup-select";

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>Spotify setup</h1>
          <p className="subtitle">
            Connect your Spotify account, then choose a playlist or album for
            each mood. Saved to <code className="inline-code">config/spotify_mood_mapping.json</code>.
          </p>
          <p className="subtitle" style={{ marginTop: 8 }}>
            <Link to="/" className="nav-inline-link">
              ← Live dashboard
            </Link>
          </p>
        </div>
      </header>

      {connectedBanner ? (
        <div className="panel setup-banner success">
          <p style={{ margin: 0 }}>
            Spotify connected. You can load your playlists below.
          </p>
          <button
            type="button"
            className="toggle-btn"
            onClick={clearConnectedParam}
          >
            Dismiss
          </button>
        </div>
      ) : null}

      <section className="panel">
        <h2>1. Account</h2>
        {status?.refresh_token_configured ? (
          <>
            <p className="small-text">
              Spotify is connected. Playlist setup below is ready.
            </p>
            <div className="button-row" style={{ marginTop: 12 }}>
              <a className="toggle-btn" href={connectHref}>
                Reconnect Spotify
              </a>
              <button type="button" className="toggle-btn" onClick={loadStatus}>
                Refresh status
              </button>
            </div>
          </>
        ) : status ? (
          <>
            <ul className="setup-list">
              <li>
                Spotify app (client id + secret):{" "}
                {status.client_configured
                  ? "configured (env or config/constants.json)"
                  : "missing — add to config/constants.json or .env"}
              </li>
              <li>User login (refresh token): not connected</li>
              <li>
                Mood mapping file:{" "}
                {status.mood_mapping_saved ? "saved" : "not saved yet"}
              </li>
            </ul>
            <div className="button-row" style={{ marginTop: 12 }}>
              <a className="toggle-btn active-btn" href={connectHref}>
                Get refresh token (Connect Spotify)
              </a>
              <button type="button" className="toggle-btn" onClick={loadStatus}>
                Refresh status
              </button>
            </div>
            <p className="small-text" style={{ marginTop: 12 }}>
              Redirect URI for your Spotify app (register exactly this; full setup in project{" "}
              <code className="inline-code">README.md</code>):
            </p>
            <p className="small-text" style={{ marginTop: 8 }}>
              <code className="inline-code">
                {status.oauth_redirect_uri ?? `${api}/spotify/oauth/callback`}
              </code>
            </p>
          </>
        ) : (
          <p className="small-text">Could not reach API — is main.py running?</p>
        )}
      </section>

      <section className="panel">
        <h2>2. Playlists per mood</h2>
        {!status?.refresh_token_configured ? (
          <>
            <p className="small-text">
              First connect Spotify to create/save a local refresh token on your
              machine. After connect, this section becomes playlist-only setup.
            </p>
            <div className="button-row" style={{ marginTop: 10 }}>
              <a className="toggle-btn active-btn" href={connectHref}>
                Get refresh token
              </a>
            </div>
          </>
        ) : null}
        {status?.refresh_token_configured ? (
          <>
        <p className="small-text">
          Pick from your library or paste an{" "}
          <code className="inline-code">open.spotify.com</code> playlist/album link.
          To use multiple playlists for one mood, add extra links as a comma-separated list.
        </p>

        <div className="setup-grid">
          <label className="setup-field">
            <span className="card-label">Calm</span>
            <select
              className={selectClass}
              value={calmSelect}
              onChange={(e) => setCalmSelect(e.target.value)}
            >
              <option value="">— choose from your library —</option>
              {candidates.map((c) => (
                <option key={`calm-${c.uri}`} value={c.uri}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              className={selectClass}
              style={{ marginTop: 8 }}
              placeholder="Optional extra links (comma-separated)"
              value={calmOverride}
              onChange={(e) => setCalmOverride(e.target.value)}
            />
          </label>

          <label className="setup-field">
            <span className="card-label">Focus</span>
            <select
              className={selectClass}
              value={focusSelect}
              onChange={(e) => setFocusSelect(e.target.value)}
            >
              <option value="">— choose from your library —</option>
              {candidates.map((c) => (
                <option key={`focus-${c.uri}`} value={c.uri}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              className={selectClass}
              style={{ marginTop: 8 }}
              placeholder="Optional extra links (comma-separated)"
              value={focusOverride}
              onChange={(e) => setFocusOverride(e.target.value)}
            />
          </label>

          <label className="setup-field">
            <span className="card-label">Hype</span>
            <select
              className={selectClass}
              value={hypeSelect}
              onChange={(e) => setHypeSelect(e.target.value)}
            >
              <option value="">— choose from your library —</option>
              {candidates.map((c) => (
                <option key={`hype-${c.uri}`} value={c.uri}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              className={selectClass}
              style={{ marginTop: 8 }}
              placeholder="Optional extra links (comma-separated)"
              value={hypeOverride}
              onChange={(e) => setHypeOverride(e.target.value)}
            />
          </label>

          <label className="setup-field">
            <span className="card-label">Deep focus (optional)</span>
            <select
              className={selectClass}
              value={deepSelect}
              onChange={(e) => setDeepSelect(e.target.value)}
            >
              <option value="">— leave empty to use focus playlist —</option>
              {candidates.map((c) => (
                <option key={`deep-${c.uri}`} value={c.uri}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              className={selectClass}
              style={{ marginTop: 8 }}
              placeholder="Optional extra links (comma-separated)"
              value={deepOverride}
              onChange={(e) => setDeepOverride(e.target.value)}
            />
          </label>
        </div>

        <div className="button-row" style={{ marginTop: 16 }}>
          <button
            type="button"
            className="toggle-btn"
            onClick={applySuggestions}
            disabled={!suggestions}
          >
            Apply smart suggestions
          </button>
          <button
            type="button"
            className="toggle-btn"
            onClick={loadSuggestions}
            disabled={loading}
          >
            {loading ? "Loading…" : "Reload my playlists"}
          </button>
          <button type="button" className="toggle-btn active-btn" onClick={saveMapping}>
            Save mapping
          </button>
        </div>
        <p className="small-text" style={{ marginTop: 10 }}>
          {lastSyncedAt
            ? `Last synced: ${lastSyncedAt}`
            : "Last synced: not yet"}
        </p>

        {message ? <p className="setup-msg ok">{message}</p> : null}
        {error ? <p className="setup-msg err">{error}</p> : null}
          </>
        ) : null}
      </section>
    </div>
  );
}
