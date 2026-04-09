import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getApiBase } from "../apiBase";
import { useEEGStream } from "../hooks/useEEGStream";
import { EEGChart } from "../components/EEGChart";
import { SAMPLE_RATE, WS_PORT } from "../constants";

const WS_URL = import.meta.env.VITE_WS_URL ?? `ws://localhost:${WS_PORT}/ws`;

const moodColors: Record<string, string> = {
  calm: "#60a5fa",
  focus: "#34d399",
  hype: "#f97316",
  deep_focus: "#a78bfa",
};

const defaultPlaylistLabels: Record<string, string> = {
  calm: "Ambient Reset",
  focus: "Deep Focus Flow",
  hype: "High Energy Boost",
  deep_focus: "Deep Focus Flow",
};

function playlistLabel(
  mood: string,
  labels: Record<string, string>,
): string {
  if (labels[mood]) return labels[mood];
  if (mood === "deep_focus" && labels.focus) return labels.focus;
  return defaultPlaylistLabels[mood] ?? mood.replace(/_/g, " ");
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function MetricCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="metric-value">{formatPercent(value)}</div>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${value * 100}%`, backgroundColor: accent }}
        />
      </div>
    </div>
  );
}

function FeatureStatCard({
  label,
  value,
  subtitle,
}: {
  label: string;
  value: number;
  subtitle?: string;
}) {
  const numericValue = Number(value);

  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="big-text">
        {Number.isFinite(numericValue) ? numericValue.toFixed(2) : "—"}
      </div>
      {subtitle ? <div className="small-text">{subtitle}</div> : null}
    </div>
  );
}

function StatusBadge({ text, color }: { text: string; color: string }) {
  return (
    <span className="status-badge" style={{ backgroundColor: color }}>
      {text}
    </span>
  );
}

function LogItem({ text, time }: { text: string; time: string }) {
  return (
    <div className="log-item">
      <span className="log-time">{time}</span>
      <span>{text}</span>
    </div>
  );
}

interface HistoryPoint {
  time: string;
  energy: number;
  focus: number;
}

interface NowPlayingTrack {
  name: string;
  artists: string[];
  album?: string | null;
  image_url?: string | null;
}

interface DashboardPlayerState {
  paused: boolean;
  is_playing: boolean;
  progress_ms?: number | null;
  track?: NowPlayingTrack | null;
}

function formatDurationMs(ms?: number | null): string {
  if (!ms || ms < 0) return "0:00";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function TinyBarChart({
  history,
  metricKey,
  color,
  title,
}: {
  history: HistoryPoint[];
  metricKey: "energy" | "focus";
  color: string;
  title: string;
}) {
  const maxHeight = 120;

  return (
    <div className="chart-card">
      <div className="chart-title">{title}</div>
      <div className="chart-bars">
        {history.map((point, index) => (
          <div key={`${metricKey}-${index}`} className="chart-bar-group">
            <div
              className="chart-bar"
              style={{
                height: `${point[metricKey] * maxHeight}px`,
                backgroundColor: color,
              }}
              title={`${point.time} - ${metricKey}: ${formatPercent(point[metricKey])}`}
            />
            <div className="chart-time">{point.time.slice(-2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyChartCard({ title }: { title: string }) {
  return (
    <div
      className="chart-card"
      style={{
        minHeight: "110px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
      }}
    >
      <div className="chart-title">{title}</div>
      <div className="small-text">Waiting for live feature updates...</div>
    </div>
  );
}

export default function LiveDashboard() {
  const { buffer, features, connected } = useEEGStream(WS_URL);
  const navigate = useNavigate();
  const api = useMemo(() => getApiBase(), []);

  const [playbackKind, setPlaybackKind] = useState<"playlist" | "pool">(
    "playlist",
  );
  const [spotifyTokenConnected, setSpotifyTokenConnected] = useState(false);
  const [playbackPaused, setPlaybackPaused] = useState(false);
  const [isSpotifyPlaying, setIsSpotifyPlaying] = useState(false);
  const [nowPlaying, setNowPlaying] = useState<NowPlayingTrack | null>(null);
  const [nowPlayingProgressMs, setNowPlayingProgressMs] = useState<number | null>(
    null,
  );
  const [playerActionBusy, setPlayerActionBusy] = useState(false);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [spotifyLabels, setSpotifyLabels] = useState<Record<string, string>>(
    {},
  );
  const [logs, setLogs] = useState([
    { time: new Date().toLocaleTimeString(), text: "Dashboard started" },
  ]);
  const prevMoodRef = useRef<string | null>(null);

  const energy = features?.energy ?? 0;
  const focus = features?.focus ?? 0;
  const mood = features?.mood ?? "calm";
  const connectionStatusText = connected
    ? "Connected to EEG stream"
    : "Connecting to EEG stream...";
  const thetaBetaRatio = features?.theta_beta_ratio ?? 0;
  const alphaSuppression = features?.alpha_suppression ?? 0;
  const neuroFeatureCards = [
    {
      label: "Theta / Beta Ratio",
      value: thetaBetaRatio,
      subtitle: "Attention-related feature from live EEG stream",
    },
    {
      label: "Alpha Suppression",
      value: alphaSuppression,
      subtitle: "Engagement-related feature from live EEG stream",
    },
  ];
  const currentPlaylist = useMemo(
    () => playlistLabel(mood, spotifyLabels),
    [mood, spotifyLabels],
  );

  useEffect(() => {
    fetch(`${api}/spotify/dashboard/playback-mode`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: null | { mode?: string }) => {
        if (!data?.mode) return;
        if (data.mode === "pool") setPlaybackKind("pool");
        else setPlaybackKind("playlist");
      })
      .catch(() => {});
  }, [api]);

  const fetchPlayerState = async () => {
    const response = await fetch(`${api}/spotify/dashboard/player`);
    if (!response.ok) return;
    const data: DashboardPlayerState = await response.json();
    setPlaybackPaused(Boolean(data.paused));
    setIsSpotifyPlaying(Boolean(data.is_playing));
    setNowPlaying(data.track ?? null);
    setNowPlayingProgressMs(
      typeof data.progress_ms === "number" ? data.progress_ms : null,
    );
  };

  useEffect(() => {
    fetchPlayerState().catch(() => {});
    const id = window.setInterval(() => {
      fetchPlayerState().catch(() => {});
    }, 5000);
    return () => window.clearInterval(id);
  }, [api]);

  useEffect(() => {
    fetch(`${api}/spotify/setup/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: null | { refresh_token_configured?: boolean }) => {
        setSpotifyTokenConnected(Boolean(data?.refresh_token_configured));
      })
      .catch(() => setSpotifyTokenConnected(false));
  }, [api]);

  useEffect(() => {
    fetch(`${api}/spotify/playlists/mapping/display`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: null | Record<string, { name?: string }>) => {
        if (!data) return;
        const next: Record<string, string> = {};
        if (data.calm?.name) next.calm = data.calm.name;
        if (data.focus?.name) next.focus = data.focus.name;
        if (data.hype?.name) next.hype = data.hype.name;
        if (data.deep_focus?.name) next.deep_focus = data.deep_focus.name;
        if (Object.keys(next).length) setSpotifyLabels(next);
      })
      .catch(() => {});
  }, [api]);

  const channels: Float32Array[] = buffer
    ? buffer.getData().map((ch) => new Float32Array(ch))
    : [];

  useEffect(() => {
    if (!features) return;

    const now = new Date().toLocaleTimeString();

    setHistory((prev) => {
      const updated = [
        ...prev,
        { time: now, energy: features.energy, focus: features.focus },
      ];
      return updated.slice(-8);
    });

    const prevMood = prevMoodRef.current;
    if (prevMood !== null && features.mood !== prevMood) {
      setLogs((prev) =>
        [
          {
            time: now,
            text: `Mood changed from ${prevMood} to ${features.mood}`,
          },
          ...prev,
        ].slice(0, 8),
      );

      if (playbackKind === "playlist") {
        const name = playlistLabel(features.mood, spotifyLabels);
        setLogs((prev) =>
          [
            {
              time: now,
              text: playbackPaused
                ? `Playback paused — holding "${name}" until resume`
                : `Playlist mode → context "${name}"`,
            },
            ...prev,
          ].slice(0, 8),
        );
      } else {
        setLogs((prev) =>
          [
            {
              time: now,
              text: playbackPaused
                ? `Playback paused — pool mode changes are locked`
                : `Pool mode → mood ${features.mood} (nearest track from CSV)`,
            },
            ...prev,
          ].slice(0, 8),
        );
      }
    }
    prevMoodRef.current = features.mood;
  }, [features, playbackKind, playbackPaused, spotifyLabels]);

  const postPlaybackMode = async (mode: "playlist" | "pool") => {
    await fetch(`${api}/spotify/dashboard/playback-mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    setPlaybackKind(mode);
  };

  const onPlaylistMode = async () => {
    await postPlaybackMode("playlist");
  };

  const onPoolMode = async () => {
    await postPlaybackMode("pool");
  };

  const onUpdatePlaylist = async () => {
    navigate("/setup");
  };

  const onPausePlayback = async () => {
    setPlayerActionBusy(true);
    try {
      const response = await fetch(`${api}/spotify/dashboard/pause`, {
        method: "POST",
      });
      if (response.ok) {
        setPlaybackPaused(true);
        setLogs((prev) =>
          [
            {
              time: new Date().toLocaleTimeString(),
              text: "Playback paused — auto-switching is locked",
            },
            ...prev,
          ].slice(0, 8),
        );
      }
    } finally {
      setPlayerActionBusy(false);
      fetchPlayerState().catch(() => {});
    }
  };

  const onResumePlayback = async () => {
    setPlayerActionBusy(true);
    try {
      const response = await fetch(`${api}/spotify/dashboard/resume`, {
        method: "POST",
      });
      if (response.ok) {
        setPlaybackPaused(false);
        setLogs((prev) =>
          [
            {
              time: new Date().toLocaleTimeString(),
              text: "Playback resumed — auto-switching unlocked",
            },
            ...prev,
          ].slice(0, 8),
        );
      }
    } finally {
      setPlayerActionBusy(false);
      fetchPlayerState().catch(() => {});
    }
  };

  const connectSpotifyHref = `${api}/spotify/oauth/authorize`;

  const moodColor = moodColors[mood] ?? "#64748b";

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>EEG-Powered Music Dashboard</h1>
          <p className="subtitle">
            Frontend dashboard for live brain metrics, mood detection, and music
            response.
          </p>
        </div>

        <div className="header-statuses">
          <StatusBadge
            text={connected ? "Connected" : "Connecting"}
            color={connected ? "#16a34a" : "#dc2626"}
          />
          <StatusBadge
            text={`Spotify: ${playbackKind === "playlist" ? "playlist" : "pool"}`}
            color="#1d4ed8"
          />
          <StatusBadge
            text={playbackPaused ? "Playback locked" : "Playback live"}
            color={playbackPaused ? "#b45309" : "#16a34a"}
          />
        </div>
      </header>

      <section className="panel" style={{ marginBottom: 18 }}>
        <h2>Live EEG Stream</h2>
        {channels.length > 0 ? (
          <EEGChart channels={channels} sampleRate={SAMPLE_RATE} />
        ) : (
          <div
            className="small-text"
            style={{ display: "flex", alignItems: "center", gap: "8px" }}
          >
            <span className="pulse-dot" />
            {connectionStatusText}
          </div>
        )}
      </section>

      <section className="top-grid">
        <div className="panel">
          <h2>Live Brain Metrics</h2>
          <div className="metrics-grid">
            <MetricCard label="Energy" value={energy} accent="#f97316" />
            <MetricCard label="Focus" value={focus} accent="#34d399" />
          </div>
        </div>

        <div className="panel">
          <h2>Current Mood</h2>
          <div className="mood-panel">
            <div
              className="mood-circle"
              style={{ backgroundColor: moodColor }}
            >
              {mood.replace(/_/g, " ").toUpperCase()}
            </div>
            <p className="mood-description">
              Mood is classified from EEG-derived energy values.
            </p>
            <div className="legend-row">
              <span
                className={`legend-pill ${mood === "calm" ? "active" : ""}`}
              >
                Calm
              </span>
              <span
                className={`legend-pill ${mood === "deep_focus" ? "active" : ""}`}
              >
                Deep focus
              </span>
              <span
                className={`legend-pill ${mood === "focus" ? "active" : ""}`}
              >
                Focus
              </span>
              <span
                className={`legend-pill ${mood === "hype" ? "active" : ""}`}
              >
                Hype
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="music-header">
          <h2>Music Control Panel</h2>
          <p className="small-text" style={{ margin: "0 0 6px 0" }}>
            {spotifyTokenConnected
              ? "Spotify token connected. You can control playback."
              : "Connect Spotify first to save a local refresh token and enable playback control."}
          </p>
          <div className="button-row">
            {spotifyTokenConnected ? (
              <button className="toggle-btn" type="button" disabled>
                Spotify connected
              </button>
            ) : (
              <a className="toggle-btn" href={connectSpotifyHref}>
                Connect Spotify (get token)
              </a>
            )}
            <button
              className="toggle-btn"
              type="button"
              onClick={() => void onUpdatePlaylist()}
            >
              Update playlist
            </button>
            <button
              className={
                playbackKind === "playlist"
                  ? "toggle-btn active-btn"
                  : "toggle-btn"
              }
              type="button"
              onClick={() => void onPlaylistMode()}
            >
              Playlist mode
            </button>
            <button
              className={
                playbackKind === "pool" ? "toggle-btn active-btn" : "toggle-btn"
              }
              type="button"
              onClick={() => void onPoolMode()}
            >
              Pool mode
            </button>
            <button
              className="toggle-btn"
              type="button"
              disabled={playerActionBusy}
              onClick={() =>
                void (playbackPaused ? onResumePlayback() : onPausePlayback())
              }
            >
              {playbackPaused ? "Resume playback" : "Pause playback"}
            </button>
          </div>
        </div>

        <div className="music-grid" style={{ marginBottom: 14 }}>
          <div className="card">
            <div className="card-label">Now playing</div>
            <div className="big-text">{nowPlaying?.name ?? "No active track"}</div>
            <div className="small-text">
              {nowPlaying?.artists?.length
                ? nowPlaying.artists.join(", ")
                : "—"}
            </div>
          </div>
          <div className="card">
            <div className="card-label">Playback status</div>
            <div className="big-text">
              {playbackPaused
                ? "Paused (locked)"
                : isSpotifyPlaying
                  ? "Playing"
                  : "Idle"}
            </div>
            <div className="small-text">
              Position: {formatDurationMs(nowPlayingProgressMs)}
            </div>
          </div>
          <div className="card">
            <div className="card-label">Album</div>
            <div className="big-text">{nowPlaying?.album || "—"}</div>
          </div>
        </div>

        {playbackKind === "playlist" ? (
          <div className="music-grid">
            <div className="card">
              <div className="card-label">Playback</div>
              <div className="big-text">Mood playlists</div>
            </div>
            <div className="card">
              <div className="card-label">Active context (by mood)</div>
              <div className="big-text">{currentPlaylist}</div>
            </div>
            <div className="card">
              <div className="card-label">Setup</div>
              <div className="small-text">
                At the beginning, playlist mode is using the default playlist mapping; set your own
                playlists above in the update playlist button.
              </div>
            </div>
          </div>
        ) : (
          <div className="music-grid">
            <div className="card">
              <div className="card-label">Playback</div>
              <div className="big-text">CSV track pool</div>
            </div>
            <div className="card">
              <div className="card-label">Behavior</div>
              <div className="small-text">
                No setup step — neuro-rave picks nearest tracks from your pool
                as EEG features update.
              </div>
            </div>
            <div className="card">
              <div className="card-label">Mood</div>
              <div className="big-text">{mood.replace(/_/g, " ")}</div>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Neuro Features</h2>
        <div className="music-grid">
          {neuroFeatureCards.map((feature) => (
            <FeatureStatCard
              key={feature.label}
              label={feature.label}
              value={feature.value}
              subtitle={feature.subtitle}
            />
          ))}
        </div>
      </section>

      <section className="charts-grid">
        {history.length > 0 ? (
          <>
            <TinyBarChart
              history={history}
              metricKey="energy"
              color="#f97316"
              title="Energy History"
            />
            <TinyBarChart
              history={history}
              metricKey="focus"
              color="#34d399"
              title="Focus History"
            />
          </>
        ) : (
          <>
            <EmptyChartCard title="Energy History" />
            <EmptyChartCard title="Focus History" />
          </>
        )}
      </section>

      <section className="panel">
        <h2>Recent Activity Log</h2>
        <div className="log-list">
          {logs.map((log, index) => (
            <LogItem key={index} time={log.time} text={log.text} />
          ))}
        </div>
      </section>
    </div>
  );
}
