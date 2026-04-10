
import { useEffect, useMemo, useRef, useState } from "react";
import { useEEGStream } from "./hooks/useEEGStream";
import { EEGChart } from "./components/EEGChart";
import { SAMPLE_RATE, WS_PORT } from "./constants";

const WS_URL = import.meta.env.VITE_WS_URL ?? `ws://localhost:${WS_PORT}/ws`;

const moodColors: Record<string, string> = {
  calm: "#60a5fa",
  focus: "#34d399",
  hype: "#f97316",
};

function getSpotifyPlaylist(mood: string): string {
  const playlists: Record<string, string> = {
    calm: "Ambient Reset",
    focus: "Deep Focus Flow",
    hype: "High Energy Boost",
  };
  return playlists[mood];
}

function getSunoPrompt(mood: string): string {
  const prompts: Record<string, string> = {
    calm: "Slow ambient pads with soft textures and peaceful atmosphere",
    focus:
      "Minimal no-vocal focus music with steady rhythm and low distraction",
    hype: "High-energy techno with driving percussion and exciting momentum",
  };
  return prompts[mood];
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
      <div className="empty-chart-placeholder">
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
      </div>
      <div className="small-text">Waiting for live feature updates...</div>
    </div>
  );
}

import { Route, Routes } from "react-router-dom";
import LiveDashboard from "./pages/LiveDashboard";
import SetupPage from "./pages/SetupPage";


export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LiveDashboard />} />
      <Route path="/setup" element={<SetupPage />} />
    </Routes>
  );
}
