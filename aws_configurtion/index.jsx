// LiveChart.jsx
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid
} from "recharts";

export function LiveChart({ history }) {
  return (
    <div style={cardStyle}>
      <SectionTitle colour="#00d4ff">Real-Time Telemetry</SectionTitle>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={history}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a3040" />
          <XAxis dataKey="time" tick={{ fill: "#4a6a7a", fontSize: 9 }}
            interval="preserveStartEnd" />
          <YAxis tick={{ fill: "#4a6a7a", fontSize: 9 }} width={35} />
          <Tooltip
            contentStyle={{
              background: "#0a1520", border: "1px solid #1a3040",
              borderRadius: 4, fontSize: 11,
              fontFamily: "'Space Mono', monospace",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 9, fontFamily: "'Space Mono', monospace" }} />
          <Line type="monotone" dataKey="pm25"       stroke="#ff6b2b"
            dot={false} strokeWidth={2} name="PM2.5 (μg/m³)" />
          <Line type="monotone" dataKey="temp"       stroke="#00d4ff"
            dot={false} strokeWidth={2} name="Temp (°C)" />
          <Line type="monotone" dataKey="congestion" stroke="#ffd600"
            dot={false} strokeWidth={2} name="Congestion (0-1)" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ZoneMap.jsx
export function ZoneMap({ summary }) {
  const zones = [
    { key: "Zone_A", label: "ZONE A", sub: "Residential" },
    { key: "Zone_B", label: "ZONE B", sub: "Industrial"  },
    { key: "Zone_C", label: "ZONE C", sub: "Commercial"  },
    { key: "Zone_D", label: "ZONE D", sub: "Transport"   },
  ];

  const statusColour = {
    GOOD:     { dot: "#00ff9d", glow: "#00ff9d", bg: "rgba(0,255,157,0.04)"  },
    WARNING:  { dot: "#ffd600", glow: "#ffd600", bg: "rgba(255,214,0,0.05)"  },
    CRITICAL: { dot: "#ff3b5c", glow: "#ff3b5c", bg: "rgba(255,59,92,0.08)" },
  };

  return (
    <div style={cardStyle}>
      <SectionTitle colour="#00d4ff">Zone Status Map</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {zones.map(({ key, label, sub }) => {
          const zoneData = summary[key] || {};
          const status   = zoneData.status || "GOOD";
          const c        = statusColour[status] || statusColour.GOOD;
          const sensors  = zoneData.sensors || [];

          return (
            <div key={key} style={{
              background: c.bg,
              border: `1px solid ${c.dot}40`,
              borderRadius: 4, padding: "12px",
              textAlign: "center",
              animation: status === "CRITICAL" ? "blink 1.2s infinite" : "none",
            }}>
              <div style={{
                width: 8, height: 8, borderRadius: "50%",
                background: c.dot,
                boxShadow: `0 0 10px ${c.glow}`,
                margin: "0 auto 6px",
              }} />
              <div style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 11, letterSpacing: 2, color: "#c8dde8",
                marginBottom: 3,
              }}>{label}</div>
              <div style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 16, color: c.dot, marginBottom: 2,
              }}>{status}</div>
              <div style={{ fontSize: 9, color: "#4a6a7a" }}>{sub}</div>
              <div style={{ fontSize: 8, color: "#2a4a5a", marginTop: 4 }}>
                {sensors.length} sensor{sensors.length !== 1 ? "s" : ""}
              </div>
            </div>
          );
        })}
      </div>
      <style>{`
        @keyframes blink {
          0%,100%{opacity:1} 50%{opacity:0.6}
        }
      `}</style>
    </div>
  );
}

// AlertFeed.jsx
export function AlertFeed({ events }) {
  const sevColour = {
    CRITICAL: "#ff3b5c",
    WARNING:  "#ffd600",
    INFO:     "#00d4ff",
  };

  return (
    <div style={cardStyle}>
      <SectionTitle colour="#ff3b5c">Alert Feed</SectionTitle>
      {events.length === 0 ? (
        <div style={{
          textAlign: "center", padding: "24px",
          color: "#4a6a7a", fontSize: 12,
        }}>✓ No active alerts</div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8,
        }}>
          {events.slice(0, 9).map((evt, i) => {
            const c = sevColour[evt.severity] || "#00d4ff";
            return (
              <div key={i} style={{
                borderLeft: `3px solid ${c}`,
                background: `${c}08`,
                padding: "10px 12px",
                borderRadius: "0 4px 4px 0",
              }}>
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  marginBottom: 4,
                }}>
                  <span style={{
                    fontFamily: "'Space Mono', monospace",
                    fontSize: 9, letterSpacing: 1.5,
                    color: c, textTransform: "uppercase",
                  }}>{evt.severity}</span>
                  <span style={{
                    fontFamily: "'Space Mono', monospace",
                    fontSize: 9, color: "#4a6a7a",
                  }}>{evt.timestamp?.slice(11, 19)}</span>
                </div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#c8dde8", marginBottom: 3 }}>
                  {evt.event_type?.replace(/_/g, " ")}
                </div>
                <div style={{ fontSize: 10, color: "#8aacba", lineHeight: 1.4 }}>
                  {evt.message?.slice(0, 80)}
                  {(evt.message?.length || 0) > 80 ? "..." : ""}
                </div>
                <div style={{
                  fontFamily: "'Space Mono', monospace",
                  fontSize: 9, color: "#4a6a7a", marginTop: 4,
                }}>
                  {evt.sensor_id} · {evt.location}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// PipelineBar.jsx
export function PipelineBar({ readings, pollCount }) {
  const sensorCount  = Object.keys(readings).length;
  const readingCount = Object.values(readings).reduce(
    (sum, arr) => sum + (arr?.length || 0), 0
  );

  const nodes = [
    { icon: "📡", name: "Sensors",      value: `${sensorCount} active`,  active: sensorCount > 0 },
    { icon: "🌫️", name: "Fog Layer",    value: "Processing",              active: true },
    { icon: "🔗", name: "API Gateway",  value: "HTTPS",                   active: true },
    { icon: "📬", name: "SQS Queue",    value: "Decoupled",               active: true },
    { icon: "λ",  name: "Lambda",       value: "Auto-scale",              active: true },
    { icon: "🗄️", name: "DynamoDB",     value: `${readingCount} records`, active: readingCount > 0 },
    { icon: "📊", name: "Dashboard",    value: `Poll #${pollCount}`,      active: true, highlight: true },
  ];

  return (
    <div style={cardStyle}>
      <SectionTitle colour="#00d4ff">AWS Cloud Pipeline — Live</SectionTitle>
      <div style={{
        display: "flex", alignItems: "center",
        overflowX: "auto", paddingBottom: 4,
      }}>
        {nodes.map((node, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
            <div style={{
              background: node.highlight ? "rgba(0,212,255,0.08)" : "#0f1e2e",
              border: `1px solid ${node.highlight ? "#00d4ff" : node.active ? "#1a4060" : "#1a3040"}`,
              borderRadius: 4, padding: "10px 14px",
              textAlign: "center", minWidth: 100,
              boxShadow: node.highlight ? "0 0 16px rgba(0,212,255,0.15)" : "none",
            }}>
              <div style={{ fontSize: 18, marginBottom: 3 }}>{node.icon}</div>
              <div style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 8, letterSpacing: 1.5,
                textTransform: "uppercase", color: "#4a6a7a",
                marginBottom: 3,
              }}>{node.name}</div>
              <div style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 10,
                color: node.active ? "#00d4ff" : "#2a4a5a",
              }}>{node.value}</div>
            </div>

            {i < nodes.length - 1 && (
              <div style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
                <div style={{
                  width: 24, height: 2,
                  background: "linear-gradient(90deg,#1a3040,#00d4ff)",
                  position: "relative", overflow: "hidden",
                }}>
                  <div style={{
                    position: "absolute", inset: 0,
                    background: "linear-gradient(90deg,transparent,rgba(0,212,255,0.8),transparent)",
                    animation: "flow 1.5s linear infinite",
                  }} />
                </div>
                <div style={{
                  width: 0, height: 0,
                  borderTop: "4px solid transparent",
                  borderBottom: "4px solid transparent",
                  borderLeft: "5px solid #00d4ff",
                }} />
              </div>
            )}
          </div>
        ))}
      </div>
      <style>{`
        @keyframes flow {
          from{transform:translateX(-100%)}
          to{transform:translateX(100%)}
        }
      `}</style>
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────
const cardStyle = {
  background: "#0a1520",
  border: "1px solid #1a3040",
  borderRadius: 4, padding: "18px 20px",
};

function SectionTitle({ children, colour = "#00d4ff" }) {
  return (
    <div style={{
      fontFamily: "'Space Mono', monospace",
      fontSize: 9, letterSpacing: 3,
      textTransform: "uppercase", color: "#4a6a7a",
      marginBottom: 12,
      display: "flex", alignItems: "center", gap: 8,
    }}>
      <div style={{
        width: 4, height: 4, borderRadius: "50%",
        background: colour, boxShadow: `0 0 8px ${colour}`,
      }} />
      {children}
    </div>
  );
}
