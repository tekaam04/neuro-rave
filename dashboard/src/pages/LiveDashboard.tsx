import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getApiBase } from "../apiBase";
import { useEEGStream } from "../hooks/useEEGStream";
import { EEGChart } from "../components/EEGChart";
import { SAMPLE_RATE, WS_PORT } from "../constants";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

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

function playlistLabel(mood: string, labels: Record<string, string>): string {
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

function HistoryLineChart({
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
  const chartData = history.map((point) => ({
    time: point.time,
    shortTime: point.time.slice(-8),
    value: Math.round(point[metricKey] * 100),
  }));

  return (
    <div className="chart-card real-chart-card">
      <div className="chart-title">{title}</div>

      <div className="real-chart-wrap">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart
            data={chartData}
            margin={{ top: 10, right: 12, left: -18, bottom: 0 }}
          >
            <CartesianGrid
              stroke="rgba(148, 163, 184, 0.12)"
              vertical={false}
            />
            <XAxis
              dataKey="shortTime"
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              width={34}
            />
            <Tooltip
              contentStyle={{
                background: "rgba(15, 23, 42, 0.96)",
                border: "1px solid rgba(120, 160, 255, 0.18)",
                borderRadius: "12px",
                color: "#e2e8f0",
              }}
              labelStyle={{ color: "#cbd5e1" }}
              formatter={(value) => {
                const n = Number(value);
                return [`${Number.isFinite(n) ? n : 0}%`, title];
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={3}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              isAnimationActive={true}
              animationDuration={500}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function EmptyChartCard({ title }: { title: string }) {
  return (
    <div className="chart-card empty-chart-card">
      <div className="chart-title">{title}</div>

      <div className="empty-chart-placeholder">
        <div className="empty-chart-line short" />
        <div className="empty-chart-line medium" />
        <div className="empty-chart-line tall" />
        <div className="empty-chart-line medium" />
        <div className="empty-chart-line short" />
      </div>

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
      return updated.slice(-20);
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
      <header className="topbar">
        <div className="topbar-text">
          <h1>EEG-Powered Music Dashboard</h1>
          <p className="subtitle">
            Frontend dashboard for live brain metrics, mood detection, and music
            response.
          </p>
        </div>

        <div className="topbar-status">
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

      <section className="hero-grid">
        <div className="card mood-hero">
          <div className="section-label">Current Mood</div>
          <div className="mood-hero-content">
            <div className="mood-hero-text">
              <h2>{mood.replace(/_/g, " ").toUpperCase()}</h2>
              <p>Mood is classified from EEG-derived energy values.</p>
              <span className="mood-meta">
                {connected ? "Live signal active" : "Waiting for signal"}
              </span>
            </div>

            <div className="mood-orb" style={{ backgroundColor: moodColor }}>
              {mood.replace(/_/g, " ").toUpperCase()}
            </div>
          </div>

          <div className="legend-row">
            <span className={`legend-pill ${mood === "calm" ? "active" : ""}`}>
              Calm
            </span>
            <span
              className={`legend-pill ${mood === "deep_focus" ? "active" : ""}`}
            >
              Deep focus
            </span>
            <span className={`legend-pill ${mood === "focus" ? "active" : ""}`}>
              Focus
            </span>
            <span className={`legend-pill ${mood === "hype" ? "active" : ""}`}>
              Hype
            </span>
          </div>
        </div>

        <div className="card eeg-status-card">
          <div className="section-label">Live EEG Status</div>

          <div className="status-list">
            <div className="status-row">
              <span className="status-dot live" />
              <span>Connected to EEG stream</span>
            </div>

            <div className="status-row">
              <span className="status-dot live" />
              <span>Receiving EEG updates</span>
            </div>

            <div className="status-row muted">
              <span>Last update: just now</span>
            </div>
          </div>

          <div className="mini-metrics">
            <div>
              <div className="mini-label">Energy</div>
              <div className="mini-value">{formatPercent(energy)}</div>
            </div>
            <div>
              <div className="mini-label">Focus</div>
              <div className="mini-value">{formatPercent(focus)}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="metrics-grid metrics-grid-four">
        <MetricCard label="Energy" value={energy} accent="#f97316" />
        <MetricCard label="Focus" value={focus} accent="#34d399" />

        {neuroFeatureCards.map((feature) => (
          <FeatureStatCard
            key={feature.label}
            label={feature.label}
            value={feature.value}
            subtitle={feature.subtitle}
          />
        ))}
      </section>

      <section className="music-section">
        <div className="music-section-header">
          <div>
            <h2>Music Control</h2>
            <p className="small-text music-helper">
              {spotifyTokenConnected
                ? "Spotify token connected. You can control playback."
                : "Connect Spotify first to save a local refresh token and enable playback control."}
            </p>
          </div>
        </div>

        <div className="music-toolbar">
          <a className="toggle-btn" href={connectSpotifyHref}>
            {spotifyTokenConnected
              ? "Reconnect Spotify"
              : "Connect Spotify (get token)"}
          </a>
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

        <div className="music-grid" style={{ marginBottom: 16 }}>
          <div className="card music-card">
            <div className="card-label">Now playing</div>
            <div className="big-text">{nowPlaying?.name ?? "No active track"}</div>
            <div className="small-text">
              {nowPlaying?.artists?.length
                ? nowPlaying.artists.join(", ")
                : "—"}
            </div>
          </div>
          <div className="card music-card">
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
          <div className="card music-card">
            <div className="card-label">Album</div>
            <div className="big-text">{nowPlaying?.album || "—"}</div>
          </div>
        </div>

        {playbackKind === "playlist" ? (
          <div className="music-grid">
            <div className="card music-card">
              <div className="card-label">Playback</div>
              <div className="big-text">Mood playlists</div>
            </div>

            <div className="card music-card">
              <div className="card-label">Active context (by mood)</div>
              <div className="big-text">{currentPlaylist}</div>
            </div>

            <div className="card music-card">
              <div className="card-label">Setup</div>
              <div className="small-text">
                Playlist mode starts from the default mood → playlist mapping until
                you set your own contexts using Update playlist.
              </div>
            </div>
          </div>
        ) : (
          <div className="music-grid">
            <div className="card music-card">
              <div className="card-label">Playback</div>
              <div className="big-text">CSV track pool</div>
            </div>

            <div className="card music-card">
              <div className="card-label">Behavior</div>
              <div className="small-text">
                No setup step — neuro-rave picks nearest tracks from your pool
                as EEG features update.
              </div>
            </div>

            <div className="card music-card">
              <div className="card-label">Mood</div>
              <div className="big-text">
                {mood.replace(/_/g, " ").toUpperCase()}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="history-grid">
        {history.length > 0 ? (
          <>
            <HistoryLineChart
              history={history}
              metricKey="energy"
              color="#f97316"
              title="Energy History"
            />
            <HistoryLineChart
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
