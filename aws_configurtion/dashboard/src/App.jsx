import { useState, useEffect, useCallback } from "react";

const API = process.env.REACT_APP_API_URL || "";
const POLL_MS = 5000;

const SENSOR_META = {
  temp_01:    { icon: "🌡️", label: "Temperature", unit: "°C",    field: "value_mean",            zone: "Zone A", warn: 30,  crit: 35   },
  temp_02:    { icon: "🌡️", label: "Temperature", unit: "°C",    field: "value_mean",            zone: "Zone C", warn: 30,  crit: 35   },
  hum_01:     { icon: "💧", label: "Humidity",    unit: "%",     field: "value_mean",            zone: "Zone A", warn: 80,  crit: 90   },
  air_01:     { icon: "🌫️", label: "PM2.5",       unit: "μg/m³", field: "pm25_mean",             zone: "Zone A", warn: 55,  crit: 80   },
  air_02:     { icon: "🌫️", label: "PM2.5",       unit: "μg/m³", field: "pm25_mean",             zone: "Zone B", warn: 55,  crit: 80   },
  air_03:     { icon: "🌫️", label: "PM2.5",       unit: "μg/m³", field: "pm25_mean",             zone: "Zone D", warn: 55,  crit: 80   },
  noise_01:   { icon: "🔊", label: "Noise",       unit: "dB",    field: "value_mean",            zone: "Zone C", warn: 75,  crit: 85   },
  noise_02:   { icon: "🔊", label: "Noise",       unit: "dB",    field: "value_mean",            zone: "Zone D", warn: 75,  crit: 85   },
  traffic_01: { icon: "🚗", label: "Congestion",  unit: "idx",   field: "congestion_index_mean", zone: "Zone D", warn: 0.7, crit: 0.85 },
  traffic_02: { icon: "🚗", label: "Congestion",  unit: "idx",   field: "congestion_index_mean", zone: "Zone C", warn: 0.7, crit: 0.85 },
};

const STATUS_C = {
  ok:   { border: "#1a3040", bg: "#0a1520",              label: "#00ff9d", text: "NOMINAL" },
  warn: { border: "#ffd600", bg: "rgba(255,214,0,0.04)", label: "#ffd600", text: "WARNING" },
  crit: { border: "#ff3b5c", bg: "rgba(255,59,92,0.07)", label: "#ff3b5c", text: "ALERT"   },
};

function getStatus(val, warn, crit) {
  if (val >= crit) return "crit";
  if (val >= warn) return "warn";
  return "ok";
}

function Card({ children, style }) {
  return (
    <div style={{ background: "#0a1520", border: "1px solid #1a3040", borderRadius: 4, padding: "18px 20px", ...style }}>
      {children}
    </div>
  );
}

function Title({ children, colour }) {
  const c = colour || "#00d4ff";
  return (
    <div style={{ fontFamily: "'Space Mono',monospace", fontSize: 9, letterSpacing: 3, textTransform: "uppercase", color: "#4a6a7a", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 4, height: 4, borderRadius: "50%", background: c, boxShadow: "0 0 8px " + c }} />
      {children}
    </div>
  );
}

export default function App() {
  const [readings,  setReadings]  = useState({});
  const [events,    setEvents]    = useState([]);
  const [summary,   setSummary]   = useState({});
  const [pollCount, setPollCount] = useState(0);
  const [lastPoll,  setLastPoll]  = useState(null);
  const [apiError,  setApiError]  = useState(false);
  const [history,   setHistory]   = useState([]);

  const fetchAll = useCallback(async () => {
    try {
      const [rRes, eRes, sRes] = await Promise.all([
        fetch(API + "/readings?limit=10&minutes=30"),
        fetch(API + "/events?limit=15"),
        fetch(API + "/summary?minutes=10"),
      ]);
      if (rRes.ok) {
        const d = await rRes.json();
        setReadings(d.readings || {});
        const pt = { time: new Date().toLocaleTimeString() };
        for (const [sid, items] of Object.entries(d.readings || {})) {
          if (!items[0]) continue;
          if (sid.startsWith("air"))     pt.pm25       = parseFloat(items[0].pm25_mean || 0);
          if (sid.startsWith("temp"))    pt.temp       = parseFloat(items[0].value_mean || 0);
          if (sid.startsWith("traffic")) pt.congestion = parseFloat(items[0].congestion_index_mean || 0);
        }
        setHistory(function(h) { return [...h.slice(-29), pt]; });
      }
      if (eRes.ok) { const d = await eRes.json(); setEvents(d.events || []); }
      if (sRes.ok) { const d = await sRes.json(); setSummary(d.zones  || {}); }
      setApiError(false);
      setLastPoll(new Date());
      setPollCount(function(c) { return c + 1; });
    } catch(e) { setApiError(true); }
  }, []);

  useEffect(function() {
    fetchAll();
    const id = setInterval(fetchAll, POLL_MS);
    return function() { clearInterval(id); };
  }, [fetchAll]);

  const critCount = events.filter(function(e) { return e.severity === "CRITICAL"; }).length;

  return (
    <div>
      <style>{"\
        * { margin:0; padding:0; box-sizing:border-box }\
        body { background:#050a0f; color:#c8dde8; font-family:Inter,sans-serif; min-height:100vh }\
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }\
        @keyframes alertPulse { 0%,100%{box-shadow:0 0 0 0 rgba(255,59,92,0)} 50%{box-shadow:0 0 0 4px rgba(255,59,92,.15)} }\
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.6} }\
        @keyframes flow { from{transform:translateX(-100%)} to{transform:translateX(100%)} }\
      "}</style>

      <header style={{ position:"sticky", top:0, zIndex:100, background:"rgba(5,10,15,0.95)", borderBottom:"1px solid #1a3040", padding:"12px 28px", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <div style={{ display:"flex", alignItems:"center", gap:16 }}>
          <div style={{ fontFamily:"'Space Mono',monospace", fontSize:22, fontWeight:700, color:"#00d4ff", letterSpacing:3 }}>
            NEXUS<span style={{ color:"#c8dde8" }}>CITY</span>
          </div>
          <div style={{ fontSize:10, letterSpacing:3, textTransform:"uppercase", color:"#4a6a7a", borderLeft:"1px solid #1a3040", paddingLeft:16 }}>Smart IoT Monitoring</div>
        </div>
        <div style={{ display:"flex", gap:24, alignItems:"center" }}>
          {[["Sensors", Object.keys(readings).length], ["Alerts", events.length], ["Polls", pollCount], ["Updated", lastPoll ? lastPoll.toLocaleTimeString() : "--"]].map(function(item) {
            return (
              <div key={item[0]} style={{ textAlign:"center" }}>
                <div style={{ fontFamily:"'Space Mono',monospace", fontSize:13, color:"#00d4ff" }}>{item[1]}</div>
                <div style={{ fontSize:9, letterSpacing:2, textTransform:"uppercase", color:"#4a6a7a" }}>{item[0]}</div>
              </div>
            );
          })}
          <div style={{ display:"flex", alignItems:"center", gap:6, background: apiError ? "rgba(255,59,92,0.08)" : "rgba(0,255,157,0.08)", border:"1px solid " + (apiError ? "rgba(255,59,92,0.3)" : "rgba(0,255,157,0.3)"), padding:"4px 12px", borderRadius:20, fontSize:10, letterSpacing:2, color: apiError ? "#ff3b5c" : "#00ff9d", fontFamily:"'Space Mono',monospace" }}>
            <div style={{ width:6, height:6, borderRadius:"50%", background: apiError ? "#ff3b5c" : "#00ff9d", animation:"pulse 1.5s infinite" }} />
            {apiError ? "OFFLINE" : "LIVE"}
          </div>
        </div>
      </header>

      {critCount > 0 && (
        <div style={{ background:"rgba(255,59,92,0.12)", borderBottom:"1px solid rgba(255,59,92,0.4)", padding:"8px 28px", color:"#ff3b5c", fontFamily:"'Space Mono',monospace", fontSize:11, letterSpacing:2 }}>
          {"🚨 " + critCount + " CRITICAL ALERT" + (critCount > 1 ? "S" : "") + " — " + ((events.find(function(e){ return e.severity==="CRITICAL"; }) || {}).message || "").slice(0,80)}
        </div>
      )}

      <main style={{ padding:"20px 28px", display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:16 }}>

        <div style={{ gridColumn:"1/4" }}>
          <Card>
            <Title>Sensor Layer — Live Readings</Title>
            <div style={{ display:"grid", gridTemplateColumns:"repeat(5,1fr)", gap:10 }}>
              {Object.entries(SENSOR_META).map(function(entry) {
                const sid  = entry[0];
                const meta = entry[1];
                const latest = ((readings[sid] || [])[0]) || {};
                const raw    = parseFloat(latest[meta.field] || 0);
                const val    = isNaN(raw) ? "--" : raw.toFixed(meta.unit === "idx" ? 2 : 1);
                const st     = raw ? getStatus(raw, meta.warn, meta.crit) : "ok";
                const c      = STATUS_C[st];
                return (
                  <div key={sid} style={{ background:c.bg, border:"1px solid "+c.border, borderRadius:4, padding:"14px 12px", textAlign:"center", animation: st === "crit" ? "alertPulse 2s infinite" : "none" }}>
                    <div style={{ fontSize:20, marginBottom:4 }}>{meta.icon}</div>
                    <div style={{ fontSize:9, letterSpacing:1.5, textTransform:"uppercase", color:"#4a6a7a", marginBottom:6 }}>{meta.label}</div>
                    <div style={{ fontFamily:"'Space Mono',monospace", fontSize:22, fontWeight:700, color:"#00d4ff" }}>{val}</div>
                    <div style={{ fontSize:10, color:"#4a6a7a", marginTop:2 }}>{meta.unit + " · " + meta.zone}</div>
                    <div style={{ fontSize:8, letterSpacing:1, marginTop:6, padding:"2px 6px", borderRadius:2, display:"inline-block", background:c.label+"18", color:c.label }}>{c.text}</div>
                    <div style={{ fontSize:8, color:"#2a4a5a", marginTop:4, fontFamily:"'Space Mono',monospace" }}>{sid}</div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

        <div style={{ gridColumn:"1/3" }}>
          <Card style={{ height:280 }}>
            <Title>Real-Time Telemetry</Title>
            <svg width="100%" height="220" style={{ overflow:"visible" }}>
              {history.length > 1 ? [
                { key:"pm25", colour:"#ff6b2b", label:"PM2.5" },
                { key:"temp", colour:"#00d4ff", label:"Temp C" },
                { key:"congestion", colour:"#ffd600", label:"Congestion" },
              ].map(function(ds, li) {
                const vals = history.map(function(p){ return p[ds.key] || 0; }).filter(function(v){ return v > 0; });
                if (!vals.length) return null;
                const min = Math.min.apply(null, vals);
                const max = Math.max.apply(null, vals) || 1;
                const W = 560, H = 180, pad = 10;
                const pts = history.map(function(p, i) {
                  const x = pad + (i / (history.length - 1)) * (W - pad * 2);
                  const y = H - pad - ((p[ds.key] || 0) - min) / (max - min) * (H - pad * 2);
                  return x + "," + y;
                }).join(" ");
                return (
                  <g key={ds.key}>
                    <polyline points={pts} fill="none" stroke={ds.colour} strokeWidth="2" />
                    <text x={W - 90} y={14 + li * 16} fill={ds.colour} fontSize="9" fontFamily="Space Mono">{ds.label}</text>
                  </g>
                );
              }) : (
                <text x="50%" y="50%" textAnchor="middle" fill="#4a6a7a" fontSize="12">Waiting for data...</text>
              )}
            </svg>
          </Card>
        </div>

        <div style={{ gridColumn:"3" }}>
          <Card>
            <Title>Zone Status Map</Title>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
              {[["Zone_A","ZONE A","Residential"],["Zone_B","ZONE B","Industrial"],["Zone_C","ZONE C","Commercial"],["Zone_D","ZONE D","Transport"]].map(function(z) {
                const status = (summary[z[0]] || {}).status || "GOOD";
                const colour = status === "CRITICAL" ? "#ff3b5c" : status === "WARNING" ? "#ffd600" : "#00ff9d";
                return (
                  <div key={z[0]} style={{ background:colour+"08", border:"1px solid "+colour+"40", borderRadius:4, padding:12, textAlign:"center", animation: status === "CRITICAL" ? "blink 1.2s infinite" : "none" }}>
                    <div style={{ width:8, height:8, borderRadius:"50%", background:colour, boxShadow:"0 0 10px "+colour, margin:"0 auto 6px" }} />
                    <div style={{ fontFamily:"'Space Mono',monospace", fontSize:11, letterSpacing:2, color:"#c8dde8", marginBottom:3 }}>{z[1]}</div>
                    <div style={{ fontFamily:"'Space Mono',monospace", fontSize:14, color:colour }}>{status}</div>
                    <div style={{ fontSize:9, color:"#4a6a7a" }}>{z[2]}</div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

        <div style={{ gridColumn:"1/4" }}>
          <Card>
            <Title colour="#ff3b5c">Alert Feed</Title>
            {events.length === 0
              ? <div style={{ textAlign:"center", padding:24, color:"#4a6a7a", fontSize:12 }}>✓ No active alerts</div>
              : <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:8 }}>
                  {events.slice(0,9).map(function(evt, i) {
                    const c = evt.severity === "CRITICAL" ? "#ff3b5c" : evt.severity === "WARNING" ? "#ffd600" : "#00d4ff";
                    return (
                      <div key={i} style={{ borderLeft:"3px solid "+c, background:c+"08", padding:"10px 12px", borderRadius:"0 4px 4px 0" }}>
                        <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
                          <span style={{ fontFamily:"'Space Mono',monospace", fontSize:9, color:c }}>{evt.severity}</span>
                          <span style={{ fontFamily:"'Space Mono',monospace", fontSize:9, color:"#4a6a7a" }}>{(evt.timestamp||"").slice(11,19)}</span>
                        </div>
                        <div style={{ fontSize:10, fontWeight:600, color:"#c8dde8", marginBottom:3 }}>{(evt.event_type||"").replace(/_/g," ")}</div>
                        <div style={{ fontSize:10, color:"#8aacba", lineHeight:1.4 }}>{(evt.message||"").slice(0,80)}</div>
                        <div style={{ fontFamily:"'Space Mono',monospace", fontSize:9, color:"#4a6a7a", marginTop:4 }}>{evt.sensor_id} · {evt.location}</div>
                      </div>
                    );
                  })}
                </div>
            }
          </Card>
        </div>

        <div style={{ gridColumn:"1/4" }}>
          <Card>
            <Title>AWS Cloud Pipeline</Title>
            <div style={{ display:"flex", alignItems:"center", overflowX:"auto", gap:0 }}>
              {[
                { icon:"📡", name:"Sensors",     value:Object.keys(readings).length + " active" },
                { icon:"🌫️", name:"Fog Layer",   value:"Processing"  },
                { icon:"🔗", name:"API Gateway", value:"HTTPS"       },
                { icon:"📬", name:"SQS Queue",   value:"Decoupled"   },
                { icon:"λ",  name:"Lambda",      value:"Auto-scale"  },
                { icon:"🗄️", name:"DynamoDB",    value:Object.values(readings).reduce(function(s,a){ return s+(a?a.length:0); },0) + " records" },
                { icon:"📊", name:"Dashboard",   value:"Poll #" + pollCount, highlight:true },
              ].map(function(node, i, arr) {
                return (
                  <div key={i} style={{ display:"flex", alignItems:"center", flexShrink:0 }}>
                    <div style={{ background: node.highlight ? "rgba(0,212,255,0.08)" : "#0f1e2e", border:"1px solid "+(node.highlight ? "#00d4ff" : "#1a4060"), borderRadius:4, padding:"10px 14px", textAlign:"center", minWidth:100 }}>
                      <div style={{ fontSize:18, marginBottom:3 }}>{node.icon}</div>
                      <div style={{ fontFamily:"'Space Mono',monospace", fontSize:8, letterSpacing:1.5, textTransform:"uppercase", color:"#4a6a7a", marginBottom:3 }}>{node.name}</div>
                      <div style={{ fontFamily:"'Space Mono',monospace", fontSize:10, color:"#00d4ff" }}>{node.value}</div>
                    </div>
                    {i < arr.length - 1 && (
                      <div style={{ display:"flex", alignItems:"center", flexShrink:0 }}>
                        <div style={{ width:24, height:2, background:"linear-gradient(90deg,#1a3040,#00d4ff)", position:"relative", overflow:"hidden" }}>
                          <div style={{ position:"absolute", inset:0, background:"linear-gradient(90deg,transparent,rgba(0,212,255,0.8),transparent)", animation:"flow 1.5s linear infinite" }} />
                        </div>
                        <div style={{ width:0, height:0, borderTop:"4px solid transparent", borderBottom:"4px solid transparent", borderLeft:"5px solid #00d4ff" }} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

      </main>
    </div>
  );
}
