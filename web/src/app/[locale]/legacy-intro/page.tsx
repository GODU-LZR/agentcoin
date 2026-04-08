"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useTheme } from "next-themes";
import { useRouter, usePathname } from "next/navigation";

type LocalManifest = {
  name?: string;
  description?: string;
  auth?: {
    passwordless?: boolean;
    shared_bearer_enabled?: boolean;
  };
};

type LocalDiscoveryItem = {
  id: string;
  family?: string;
  title: string;
  version?: string;
  type?: string;
  protocols?: string[];
  capabilities?: string[];
  help_summary?: string;
  agentcoin_compatibility?: {
    attachable_today?: boolean;
    preferred_integration?: string;
    notes?: string[];
  };
};

type LocalManagedRegistration = {
  registration_id: string;
  discovered_id: string;
  title?: string;
  family?: string;
  type?: string;
  publisher?: string;
  protocols?: string[];
  preferred_integration?: string;
  integration_candidates?: string[];
  attachable_today?: boolean;
  launch_command?: string[];
  launch_cwd?: string | null;
  launch_env?: Record<string, string>;
  status?: string;
  pid?: number | null;
  transport?: string;
  registered_at?: string;
  started_at?: string | null;
  stopped_at?: string | null;
  last_error?: string | null;
  last_exit_code?: number | null;
};

type LocalAcpSessionSummary = {
  turn_count?: number;
  active_phase?: string;
  pending_request_ids?: string[];
  latest_server_frame_received_at?: string | null;
};

type LocalAcpIntent = {
  server_session_id?: string;
  mapping?: {
    agentcoin_task_id?: string;
  };
  request?: {
    id?: string;
  };
};

type LocalAcpParsedContentItem = {
  type?: string;
  text?: string;
};

type LocalAcpParsed = {
  result?: {
    content?: LocalAcpParsedContentItem[];
  };
  [key: string]: unknown;
};

type LocalAcpFrame = {
  raw?: string;
  received_at?: string;
  parsed?: LocalAcpParsed;
};

type LocalAcpSession = {
  session_id: string;
  registration_id: string;
  protocol?: string;
  transport?: string;
  status?: string;
  process_state?: string;
  pid?: number | null;
  handshake_state?: string;
  protocol_state?: string;
  initialize_sent?: boolean;
  server_frames_seen?: number;
  opened_at?: string;
  updated_at?: string;
  closed_at?: string;
  notes?: string[];
  initialize_response_frame?: LocalAcpFrame;
  latest_server_frame?: LocalAcpFrame;
  task_response_frame?: LocalAcpFrame;
  latest_task_response_frame?: LocalAcpFrame;
  last_task_request_intent?: LocalAcpIntent;
  task_response_captured?: boolean;
  summary?: LocalAcpSessionSummary;
};

type LocalAcpBoundary = {
  transport_ready?: boolean;
  protocol_messages_implemented?: boolean;
  server_response_parsing_implemented?: boolean | string;
  notes?: string[];
};

type LocalAgentTarget = {
  id: string;
  name: string;
  angle: number;
  x: number;
  y: number;
};

type RemotePeer = {
  peer_id: string;
  name?: string;
  url?: string;
  overlay_endpoint?: string;
  tags?: string[];
  enabled?: boolean;
};

type RemotePeerCard = {
  peer_id?: string;
  card?: {
    name?: string;
    description?: string;
    protocols?: string[];
  };
  identity_trust?: {
    aligned?: boolean;
    requires_review?: boolean;
    severity?: string;
  };
};

type RemotePeerHealth = {
  peer_id?: string;
  status?: string;
  last_error?: string;
  failures?: number;
  cooldown_until?: string | null;
  blacklisted_until?: string | null;
};

type LocalTaskItem = {
  id: string;
  status?: string;
  kind?: string;
  role?: string;
  payload?: {
    attachments?: unknown[];
    input?: string | { prompt?: string; content?: string; text?: string; query?: string; instruction?: string };
    _runtime?: {
      prompt?: string;
    };
  };
  semantics?: {
    summary?: string;
    title?: string;
  };
  result?: unknown;
  completed_at?: string | null;
};

type LocalTaskAttachment = {
  id: string;
  name: string;
  mime_type: string;
  kind: string;
  size: number;
  data_url: string;
  text_preview?: string;
};

type TaskMediaAsset = {
  id: string;
  label: string;
  mimeType: string;
  kind: string;
  source: string;
  size?: number;
  dataUrl?: string;
  text?: string;
};

const ASCII_ART = `
     _                    _    _____      _         
    / \\                  | |  / ____|    (_)        
   / _ \\   __ _  ___ _ __| |_| |     ___  _ _ __  
  / /_\\ \\ / _\` |/ _ \\ '__| __| |    / _ \\| | '_ \\ 
 / ____ \\ (_| |  __/ |  | |_| |___| (_) | | | | |
/_/    \\_\\__, |\\___|_|   \\__|\\_____\\___/|_|_| |_|
          __/ |                                     
         |___/                                      
`;

// Earth texture map (equirectangular projection) - procedurally generated
const EARTH_TEXTURE: string[] = [
  "................................................................................................................................................",
  ".........................................................,.,,...................................................................................",
  "...........................,..<-.l.JJrJJ@c..<-JZddddddaadaadadMd.............JJZ,..............................l-1..............................",
  "......................l/<,......,.<l,-ll.........-ddadddddaa@@Mr..............................r1..........1dMadaZadJ/...........................",
  ".......rccccr-<<..l//<l<.-cJZZZ,.1Z-..J-.caMZ.....l<Zdaaaa@aZJ<................</ddM/...........<<.cZ-ZdddJJJdJZMaaMadZZda1JaZccdaJZaZrr,,l<-<,,",
  "../..<rcaJZdJZZZdZJJcadddaaaadadaa@@Jl<..l-JJ--....rZda@......./Jc...........ZMMc.Zaad.,ddJJZZZrMdcaadadZdaJZdaaaadadaMMddZadaadaddMZdZZaM@aJZac",
  "......1/dZJ<-,1/ZaaaadadZZdddaaaa@.......JMa........../...................r@a@@..rrr1JZaardZZddd@aaaddddddadJdaaaddddZddZdZZdaZaMddccJ..l<-l,...",
  ".................../aaadddaddaaaMadJZ-l..rdZdZdc.....................,r,.../,/../dZZdadadZddZdJZ@aZZddMddZZJZZZZdddddaaaaMaaaac.......<dJ.......",
  ".....................ZdddaaaadaaaddddaZc/ZdaaZZZJ1....................</,1dJJZJcJZddaaaMad@dZdZaM@ZadZJZJrcJMaZaadddaaaadMMaZdMZ,,..............",
  "......................<JZZdZdddaMdMadaaMZ@ad@d,........................-rd/aaJMacZ@M-c-ccd....aaMZadaMadZMMdaadMaaaaaddd@MadarZ<................",
  "......................-dadaZadaaaaMMaZadJad1.........................daac..../,,aad..-,.lad/.<@ZJdZJdcZMMM@MadaaaaaaaaM@MdJM....<...............",
  ".......................rdMdddaMMMMd@aJZa@-...........................11-..,<.......-rZZ@Madd.,ZZZJJZZaaZJJJZaZddaaaaa@Zc..lr.../,...............",
  "........................./ZJaaMaM@MdMa@c.............................rMMM@dJ/J..c<....ZdMMradadaMaaM@adadaaaaaaaa@Ma@@dd<...<...................",
  "........................../lZaa@@......r...........................1aaaMaaddaadMaJcdZcradaaJ.ZMadZ@MJJaM@@@@@@JdMaZMMdJd,.......................",
  ".............................,aM@......l..........................dddaadddMMaadZddaMaJ.,aaM@dJJ/...,JZMZda@dJdada@@MZJ-.,.......................",
  "..............................ldaZ</r......1......................adMaadaMaaaaM@daaMdaa..aaaZZJ......1adaa....aMM@l.....,.......................",
  "....................................dar..........................1aJZadaaaaaMaadZdaaaaZa<r@...........d@.......cdaZr....,.......................",
  "......................................1,-<M,@d@-...................ddaM@dMa@@addZdaaaZZMJaaM,..........<.......c..........,.....................",
  "........................................./@ZZZd@MJZ.......................1JMaMMaadZdZZa@a@...................1.r<....J<........................",
  "........................................-@aaMMaZaZ@a........................d@MaaaZJadZ@a.......................d/.,Zd@.........................",
  "........................................MMaddadadJZdcdJcZ....................ddZdddaadad.........................r......l.....Z@Jc..............",
  ".........................................@ZaadJJdZaMZZdaa@...................1dddadadaac..................................1.....l..1............",
  "..........................................aJJaaZdZdMJdMM/....................JaaaaadMaM@....................................c@l..,..............",
  "............................................da@a@cZMdaZ@.....................daaaaada@c...c@.............................cadaZa@drJ.............",
  "............................................r@@MMJaZdJc.......................Jaadad@a...<M..........................<caddddda@@@ddM,...........",
  "............................................d@@MaZZa/.........................rdaddd@.................................daaaMaM@dZZdMMal..........",
  "............................................@d@ada@............................<aM@d..................................-a@MJl./acZaZc@...........",
  "...........................................-@@@da...............................................................................cZcd............",
  "..........................................,aaM<...................................................................................l..........<l.",
  "..........................................1dMl.............................................................................................c....",
  "..........................................r@1...................................................................................................",
  "............................................l...................................................................................................",
  "................................................................................................................................................",
  "...............................................l................................................................................................",
  "...........................................<,/r......................................,..1cJJZdZZZZaZ...-JJZdddddddMdddZZddddddddadJr/1l.........",
  ".......................l..l....lJrrrc1ll1-1rrZ@r..................rcZZdZdddaaaMdJddadddaaacrJaaaaddJZJr..cZdaaZdZZMJ1adZaMadadl-daaaaaaM@@-.....",
  ".........,rdcJdMMMaaadaaddaddJZZdadddaZr/...........</,...rdZZMaMMaadJJZcrr-l...rcJddddcr-...-1l...........JdaaaaaaaaaaadcrrJad<1JaaaaM@@1......",
  "...........,,.,,,ll<<,<llllllll<l<ll,llllll.........,...,,,ll,,lll...,.....l,..................................,llllllllll<lllllllllllll........",
  "................................................................................................................................................"
];

function renderEarthSphere(angle: number, large: boolean = true): string {
  const W = 160;
  const H = 60;
  const R = 28;
  const tH = EARTH_TEXTURE.length, tW = EARTH_TEXTURE[0].length;
  const buf = new Array(W * H).fill(' ');
  const zbuf = new Array(W * H).fill(-999);
  const cosA = Math.cos(angle), sinA = Math.sin(angle);

  for (let theta = 0; theta < 6.2832; theta += 0.02) {
    const sinT = Math.sin(theta), cosT = Math.cos(theta);
    for (let phi = 0; phi < 6.2832; phi += 0.02) {
      const sinP = Math.sin(phi), cosP = Math.cos(phi);

      const x = R * sinT * cosP;
      const y = R * sinT * sinP;
      const z = R * cosT;

      let u = Math.atan2(x, z);
      let v = Math.atan2(-y, Math.sqrt(x * x + z * z));
      let tc = Math.floor((u / (2 * Math.PI) + 0.5) * (tW - 1));
      let tr = Math.floor((v / Math.PI + 0.5) * (tH - 1));

      if (tc < 0) tc = 0; if (tc >= tW) tc = tW - 1;
      if (tr < 0) tr = 0; if (tr >= tH) tr = tH - 1;
      let ch = EARTH_TEXTURE[tr][tc] || ' ';

      const rx = x * cosA + z * sinA;
      const rz = -x * sinA + z * cosA;

      const sx = Math.floor(W / 2 + 2.0 * rx);
      const sy = Math.floor(H / 2 - 1.0 * y);

      if (rz > 0 && sx >= 0 && sx < W && sy >= 0 && sy < H) {
        let idx = sx + W * sy;
        if (rz > zbuf[idx]) {
          buf[idx] = ch;
          zbuf[idx] = rz;
        }
      }
    }
  }

  // ==== 绘制卫星轨道 ====
  const SATS = [
    { text: " [ NODE_ALPHA ] ", cr: R + 6, speed: 1.5, offset: 0, hover: -5 },
    { text: " < ALICE > ", cr: R + 9, speed: 0.8, offset: 2.1, hover: 6 },
    { text: " >> RELAY_0 << ", cr: R + 13, speed: -1.2, offset: 1.2, hover: -12 },
    { text: " == AGENT_X == ", cr: R + 16, speed: 0.5, offset: 4.5, hover: 10 },
    { text: " // SYNC // ", cr: R + 7, speed: -1.7, offset: 0.8, hover: 16 }
  ];

  for (let s of SATS) {
    let sA = angle * s.speed + s.offset;
    let rx = s.cr * Math.cos(sA);
    let rz = s.cr * Math.sin(sA);
    let ry = s.hover;

    let sx = Math.floor(W / 2 + 2.0 * rx);
    let sy = Math.floor(H / 2 - 1.0 * ry);
    
    let halfL = Math.floor(s.text.length / 2);
    for (let i = 0; i < s.text.length; i++) {
        let drawX = sx - halfL + i;
        if (drawX >= 0 && drawX < W && sy >= 0 && sy < H) {
            let idx = drawX + W * sy;
            if (rz > zbuf[idx] - 2) {
               buf[idx] = s.text[i];
               zbuf[idx] = rz;
            }
        }
    }
  }

  const lines: string[] = [];
  for (let r = 0; r < H; r++) lines.push(buf.slice(r * W, (r + 1) * W).join(''));
  return lines.join('\n');
}

// ─── Backdrop: Types & Helpers ───────────────────────────────────────────────
type BackdropBeam = {
  x: number;            // CSS-pixel x position
  z: number;            // depth 0(far) – 1(near)
  speed: number;        // fall speed factor
  phase: number;        // time offset
  segLen: number;       // visible segment height as 0–1 of wall height
  baseWidth: number;    // core pixel width
  intensity: number;    // base brightness 0–1
  isDotted: boolean;    // dot-chain vs solid bar
  breatheRate: number;
  breathePhase: number;
  // Pre-computed DoF values (avoid re-calc per frame)
  blur: number;
  blurW: number;
  blurA: number;
};

type DustMote = {
  x: number; y: number; z: number;
  vx: number; vy: number;
  alpha: number; phase: number;
  blur: number;
};

function _bh(i: number, k: number): number {
  const v = Math.sin((i + 1) * k) * 43758.5453;
  return v - Math.floor(v);
}

function _dof(z: number): number {
  if (z >= 0.25 && z <= 0.60) return 0;
  if (z < 0.25) return (0.25 - z) / 0.25;
  return (z - 0.60) / 0.40;
}

let _dustMotes: DustMote[] | null = null;
function _getDust(): DustMote[] {
  if (_dustMotes) return _dustMotes;
  _dustMotes = Array.from({ length: 40 }, (_, i) => {
    const z = _bh(i, 419.9);
    const blur = _dof(z);
    return {
      x: _bh(i, 173.3), y: _bh(i, 311.7), z,
      vx: (_bh(i, 733.1) - 0.5) * 0.00004,
      vy: -0.00002 - _bh(i, 257.8) * 0.00008,
      alpha: 0.15 + _bh(i, 529.9) * 0.5,
      phase: _bh(i, 641.3) * Math.PI * 2,
      blur,
    };
  });
  return _dustMotes;
}

// Cached gradient objects (recreated only on resize)
let _cachedGradients: {
  w: number; h: number;
  atm: CanvasGradient; topFade: CanvasGradient; botFade: CanvasGradient;
  scanline: CanvasPattern | null;
} | null = null;

function _getGradients(ctx: CanvasRenderingContext2D, w: number, h: number) {
  if (_cachedGradients && _cachedGradients.w === w && _cachedGradients.h === h) return _cachedGradients;

  const atm = ctx.createRadialGradient(w * 0.32, h * 0.4, 0, w * 0.32, h * 0.4, w * 0.72);
  atm.addColorStop(0, 'rgba(14,14,24,0.5)');
  atm.addColorStop(0.4, 'rgba(5,5,10,0.15)');
  atm.addColorStop(1, 'rgba(0,0,0,0)');

  const topFade = ctx.createLinearGradient(0, 0, 0, h * 0.12);
  topFade.addColorStop(0, 'rgba(0,0,0,0.7)');
  topFade.addColorStop(1, 'rgba(0,0,0,0)');

  const botFade = ctx.createLinearGradient(0, h * 0.86, 0, h);
  botFade.addColorStop(0, 'rgba(0,0,0,0)');
  botFade.addColorStop(1, 'rgba(0,0,0,0.45)');

  // Pre-render scanline pattern (3px repeat: 1px dark + 2px transparent)
  let scanline: CanvasPattern | null = null;
  if (typeof OffscreenCanvas !== 'undefined') {
    const oc = new OffscreenCanvas(1, 3);
    const oCtx = oc.getContext('2d');
    if (oCtx) {
      oCtx.fillStyle = 'rgba(0,0,0,0.06)';
      oCtx.fillRect(0, 0, 1, 1);
      scanline = ctx.createPattern(oc, 'repeat');
    }
  }

  _cachedGradients = { w, h, atm, topFade, botFade, scanline };
  return _cachedGradients;
}

function createBackdropBeams(width: number): BackdropBeam[] {
  const n = Math.max(80, Math.floor(width / 12));
  return Array.from({ length: n }, (_, i) => {
    const s = _bh(i, 127.1), d = _bh(i, 311.7), u = _bh(i, 781.3);
    const v = _bh(i, 547.9), w = _bh(i, 913.2), q = _bh(i, 1031.5);

    const z = d < 0.12 ? d * 2.5 : d < 0.88 ? 0.3 + (d - 0.12) * 0.46 : 0.65 + (d - 0.88) * 2.9;
    const blur = _dof(z);
    const blurW = 1 + blur * 7;
    const blurA = 1 / (1 + blur * 2.8);

    let xN: number;
    if (z > 0.68) xN = s * 0.55;
    else if (z > 0.28) xN = 0.04 + s * 0.92;
    else xN = 0.2 + s * 0.75;

    const isDotted = u < 0.30;

    return {
      x: xN * width,
      z, speed: 18 + s * 52,
      phase: s * 5500 + i * 53,
      segLen: isDotted ? (0.4 + w * 0.6) : (0.2 + w * 0.8),
      baseWidth: isDotted ? (0.8 + (1 - blur) * 2.5) : (0.3 + (1 - blur) * 2.8),
      intensity: 0.06 + (1 - blur * 0.65) * (0.3 + (1 - blur) * 0.64),
      isDotted,
      breatheRate: 0.25 + q * 2.0,
      breathePhase: v * Math.PI * 2,
      blur, blurW, blurA,
    };
  });
}

function drawBackdropScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  timeMs: number,
  beams: BackdropBeam[],
): void {
  const t = timeMs * 0.001;
  const grads = _getGradients(ctx, width, height);

  // ── Perspective geometry (constants) ──────────────────
  const floorLY = height * 0.82;
  const floorRY = height * 0.30;
  const hSlope = (floorRY - floorLY) / width;
  const vpX = width * 0.72;
  const vpY = floorLY + hSlope * vpX - height * 0.04;

  // ── 1. Background ────────────────────────────────────
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = grads.atm;
  ctx.fillRect(0, 0, width, height);

  // ── 2. Vertical beam wall (batched draw calls) ────────
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(width, 0);
  ctx.lineTo(width, floorRY + 1); ctx.lineTo(0, floorLY + 1);
  ctx.closePath();
  ctx.clip();
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#fff';
  ctx.lineCap = 'butt';

  // Group beams by approximate alpha-bucket to reduce state changes
  // Process solid beams: batch strokes by glow layer
  const solidBeams: Array<{ bx: number; sBot: number; sTop: number; wallH: number; bw: number; bi: number; blurA: number }> = [];

  for (const b of beams) {
    const wallH = floorLY + hSlope * b.x;
    if (wallH < 5) continue;

    const breathe = 0.6 + 0.4 * Math.sin(t * b.breatheRate + b.breathePhase);
    const bi = b.intensity * breathe;
    if (bi < 0.008) continue;

    const segH = b.segLen * wallH;
    const cycle = wallH + segH;
    const off = ((t * b.speed + b.phase) % cycle);
    const sBot = Math.min(wallH, off);
    const sTop = Math.max(0, off - segH);
    if (sBot - sTop < 1) continue;

    const bw = b.baseWidth * b.blurW;

    if (b.isDotted) {
      // Dot-chain: batch all dots into a single path per alpha level
      const gap = Math.max(bw * 4, 6);
      const dotOff = (t * b.speed * 0.6 + b.phase) % gap;
      const r = bw * 0.6;
      const useRect = r < 1.5;
      let y = sBot - dotOff;

      // Collect dots, draw in one pass
      while (y >= sTop - gap) {
        if (y >= sTop && y <= sBot) {
          const edgeDist = Math.min(y - sTop, sBot - y);
          const edgeF = Math.min(1, edgeDist / (segH * 0.15 + 1));
          const a = bi * b.blurA * edgeF;
          if (a > 0.01) {
            // Glow halo (only if significant blur)
            if (b.blurW > 1.5 || r > 2) {
              ctx.globalAlpha = a * 0.1;
              ctx.beginPath(); ctx.arc(b.x, y, r * 3, 0, 6.283); ctx.fill();
            }
            ctx.globalAlpha = a * 0.85;
            if (useRect) {
              const sz = r * 2;
              ctx.fillRect(b.x - sz * 0.5, y - sz * 0.5, sz, sz);
            } else {
              ctx.beginPath(); ctx.arc(b.x, y, r, 0, 6.283); ctx.fill();
            }
          }
        }
        y -= gap;
      }
    } else {
      solidBeams.push({ bx: b.x, sBot, sTop, wallH, bw, bi, blurA: b.blurA });
    }
  }

  // Solid beams: batch each glow layer into a single path
  if (solidBeams.length > 0) {
    // Layer 0: base glow (full pillar, very dim)
    ctx.beginPath();
    let hasBase = false;
    for (const s of solidBeams) {
      const a = s.bi * s.blurA * 0.12;
      if (a < 0.005) continue;
      // We approximate: use median alpha for the batch
      if (!hasBase) { ctx.globalAlpha = 0.04; ctx.lineWidth = 12; hasBase = true; }
      ctx.moveTo(s.bx, s.wallH); ctx.lineTo(s.bx, 0);
    }
    if (hasBase) ctx.stroke();

    // Layer 1: outermost glow
    ctx.beginPath();
    ctx.globalAlpha = 0.015;
    for (const s of solidBeams) { ctx.lineWidth = s.bw * 26; ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); }
    // Since lineWidth varies per beam, we can't fully batch — draw per-beam but skip beginPath overhead:
    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.02;
      ctx.lineWidth = s.bw * 26;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    // Layer 2: mid glow
    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.07;
      ctx.lineWidth = s.bw * 9;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    // Layer 3: tight glow
    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.22;
      ctx.lineWidth = s.bw * 3;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    // Layer 4: core
    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.78;
      ctx.lineWidth = Math.max(0.5, s.bw * 0.65);
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }
  }

  ctx.globalAlpha = 1;
  ctx.restore();

  // ── 3. Perspective floor ──────────────────────────────
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, floorLY); ctx.lineTo(width, floorRY);
  ctx.lineTo(width, height); ctx.lineTo(0, height);
  ctx.closePath();
  ctx.clip();

  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#fff';

  // Radial lines: batch minor lines into one path
  ctx.beginPath();
  ctx.globalAlpha = 0.03;
  ctx.lineWidth = 0.5;
  for (let c = -36; c <= 36; c++) {
    if (c % 4 === 0) continue; // skip major
    const r = c / 36;
    const a = 0.03 * (1 - Math.abs(r) * 0.55);
    if (a < 0.005) continue;
    const ex = vpX + r * width * 3.2;
    ctx.moveTo(vpX, vpY); ctx.lineTo(ex, height * 1.4);
  }
  ctx.stroke();

  // Major radial lines (need setLineDash, individual)
  ctx.setLineDash([height * 0.02, height * 0.01, height * 0.008, height * 0.018]);
  ctx.lineDashOffset = t * 22;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  for (let c = -36; c <= 36; c += 4) {
    const r = c / 36;
    const a = 0.14 * (1 - Math.abs(r) * 0.55);
    if (a < 0.005) continue;
    ctx.moveTo(vpX, vpY); ctx.lineTo(vpX + r * width * 3.2, height * 1.4);
  }
  ctx.globalAlpha = 0.1;
  ctx.stroke();
  ctx.setLineDash([]);

  // Horizontal receding lines — batch into one path
  ctx.beginPath();
  ctx.lineWidth = 0.7;
  ctx.globalAlpha = 0.1;
  for (let row = 0; row < 20; row++) {
    const dep = Math.pow((row + 1) / 20, 2.0);
    const yL = vpY + (floorLY + height * 0.25 - vpY) * (1 + dep * 5.5);
    const yR = vpY + (floorRY + height * 0.25 - vpY) * (1 + dep * 5.5);
    ctx.moveTo(0, yL); ctx.lineTo(width, yR);
  }
  ctx.stroke();

  // Floor intersection dots — batch all into two paths (glow + core)
  ctx.fillStyle = '#fff';
  const glowPath = new Path2D();
  const corePath = new Path2D();
  for (let ri = -10; ri <= 10; ri++) {
    const rx = ri / 10;
    const endX = vpX + rx * width * 2.2;
    for (let di = 1; di <= 6; di++) {
      const dist = Math.pow(di / 6, 2.2) * 0.8;
      const px = vpX + (endX - vpX) * dist;
      const py = vpY + (height * 1.3 - vpY) * dist;
      const fY = floorLY + hSlope * px;
      if (py < fY - 2 || py > height + 3) continue;
      const near = 1 - dist;
      const flicker = 0.5 + 0.5 * Math.sin(ri * 31 + di * 17 + t * 3.5);
      const a = near * flicker * 0.6;
      if (a < 0.02) continue;
      const sz = 0.8 + near * 2;
      glowPath.rect(px - sz * 2, py - sz * 2, sz * 4, sz * 4);
      corePath.rect(px - sz * 0.5, py - sz * 0.5, sz, sz);
    }
  }
  ctx.globalAlpha = 0.08;
  ctx.fill(glowPath);
  ctx.globalAlpha = 0.4;
  ctx.fill(corePath);

  // Beam reflections on floor — batch glow and core paths
  ctx.strokeStyle = '#fff';
  for (const b of beams) {
    if (b.isDotted || b.intensity < 0.25) continue;
    const bx = b.x;
    const by = floorLY + hSlope * bx;
    const dx = bx - vpX, dy = by - vpY;
    if (Math.abs(dy) < 1) continue;
    const sl = dx / dy;
    const rLen = height * 0.22 * b.intensity;
    const ex = bx + sl * rLen, ey = by + rLen;
    const br = 0.6 + 0.4 * Math.sin(t * b.breatheRate + b.breathePhase);
    const a = b.intensity * br * 0.25;
    ctx.globalAlpha = a * 0.06;
    ctx.lineWidth = b.baseWidth * 7;
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.globalAlpha = a * 0.5;
    ctx.lineWidth = Math.max(0.6, b.baseWidth * 1.2);
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ex, ey); ctx.stroke();
  }
  ctx.restore();
  ctx.globalAlpha = 1;

  // ── 4. Dust motes (minimal) ───────────────────────────
  const dust = _getDust();
  ctx.fillStyle = '#fff';
  for (const m of dust) {
    const mx = ((m.x + t * m.vx * 800) % 1.08 + 1.08) % 1.08;
    const my = ((m.y + t * m.vy * 800) % 1.15 + 1.15) % 1.15;
    const px = mx * width, py = my * height;
    const pulse = 0.45 + 0.55 * Math.sin(t * 1.3 + m.phase);
    const a = m.alpha * pulse / (1 + m.blur * 2.5);
    if (a < 0.01) continue;
    if (m.blur > 0.35) {
      const r = 4 + m.blur * 16;
      ctx.globalAlpha = a * 0.05;
      ctx.beginPath(); ctx.arc(px, py, r, 0, 6.283); ctx.fill();
      ctx.globalAlpha = a * 0.18;
      ctx.beginPath(); ctx.arc(px, py, r * 0.45, 0, 6.283); ctx.fill();
      ctx.globalAlpha = a;
      ctx.fillRect(px - 1, py - 1, 2, 2);
    } else {
      ctx.globalAlpha = a;
      ctx.fillRect(px - 0.7, py - 0.7, 1.4, 1.4);
    }
  }
  ctx.globalAlpha = 1;

  // ── 5. Edge vignettes + scanlines ─────────────────────
  ctx.fillStyle = grads.topFade;
  ctx.fillRect(0, 0, width, height * 0.12);
  ctx.fillStyle = grads.botFade;
  ctx.fillRect(0, height * 0.86, width, height * 0.14);

  // Scanlines via cached pattern (single fillRect vs hundreds)
  if (grads.scanline) {
    ctx.fillStyle = grads.scanline;
    ctx.fillRect(0, 0, width, height);
  } else {
    ctx.fillStyle = 'rgba(0,0,0,0.06)';
    for (let sy = 0; sy < height; sy += 3) {
      ctx.fillRect(0, sy, width, 1);
    }
  }
}

// ASCII Radar Scanner
const RADAR_AGENTS = [
  { name: 'GitHub Copilot', angle: Math.PI / 4, r: 6, x: 8, y: -4 },
  { name: 'Claude Code', angle: Math.PI * 3/4, r: 8, x: -11, y: -5 },
  { name: 'OpenAI Codex', angle: Math.PI * 5/4, r: 5, x: -7, y: 3 },
  { name: 'openclaw', angle: Math.PI * 7/4, r: 9, x: 12, y: 6 }
];

const DEFAULT_RADAR_TARGETS: LocalAgentTarget[] = RADAR_AGENTS.map((agent) => ({
  id: agent.name,
  name: agent.name,
  angle: agent.angle,
  x: agent.x,
  y: agent.y,
}));

const RADAR_SLOTS: Array<Pick<LocalAgentTarget, "angle" | "x" | "y">> = [
  { angle: Math.PI / 6, x: 11, y: -5 },
  { angle: Math.PI / 2.8, x: 6, y: -7 },
  { angle: Math.PI / 1.4, x: -9, y: -5 },
  { angle: Math.PI * 1.15, x: -12, y: 2 },
  { angle: Math.PI * 1.45, x: -4, y: 6 },
  { angle: Math.PI * 1.8, x: 9, y: 5 },
  { angle: Math.PI * 0.1, x: 13, y: 1 },
  { angle: Math.PI * 0.85, x: -1, y: -8 },
];

function buildLocalAgentTargets(items: LocalDiscoveryItem[]): LocalAgentTarget[] {
  return items.map((item, index) => {
    const slot = RADAR_SLOTS[index % RADAR_SLOTS.length];
    return {
      id: item.id,
      name: item.title,
      angle: slot.angle,
      x: slot.x,
      y: slot.y,
    };
  });
}

function normalizeNodeEndpoint(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function buildLocalNodeProxyUrl(endpoint: string, path: string): string {
  const params = new URLSearchParams({
    endpoint: normalizeNodeEndpoint(endpoint),
    path,
  });
  return `/api/local-node?${params.toString()}`;
}

function fetchLocalNode(endpoint: string, path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(buildLocalNodeProxyUrl(endpoint, path), options);
}

function localNodeProxyErrorMessage(code: string | undefined, fallback: string): string {
  switch (code) {
    case "endpoint-and-path-are-required":
      return "[Node Request Error] 本地节点请求缺少 endpoint 或 path。";
    case "invalid-local-node-endpoint":
      return "[Node Request Error] 本地节点地址无效，当前只允许回环地址。";
    case "local-node-unreachable":
      return "[Node Offline] 无法通过同源代理连接本地节点，请确认 127.0.0.1:8080 已启动。";
    default:
      return fallback;
  }
}

async function readLocalNodeFailure(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json();
    const code = typeof payload?.error === "string" ? payload.error : undefined;
    return localNodeProxyErrorMessage(code, fallback);
  } catch {
    return fallback;
  }
}

function discoveryBadge(item: LocalDiscoveryItem): string {
  const raw = (item.family || item.title || "AGENT").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  return (raw || "AGT").slice(0, 3);
}

function discoverySummary(item: LocalDiscoveryItem): string {
  if (item.help_summary) return item.help_summary;
  if (item.agentcoin_compatibility?.preferred_integration) {
    return item.agentcoin_compatibility.preferred_integration;
  }
  if (item.capabilities?.length) return item.capabilities.slice(0, 3).join(" / ");
  if (item.protocols?.length) return item.protocols.join(" / ");
  return item.type || "";
}

function buildAuthHeaders(token: string): HeadersInit {
  return {
    Accept: "application/json",
    Authorization: `Bearer ${token.trim()}`,
  };
}

function remotePeerCardFor(peerId: string, cards: RemotePeerCard[]): RemotePeerCard | undefined {
  return cards.find((item) => String(item.peer_id || "").trim() === peerId);
}

function remotePeerHealthFor(peerId: string, healthItems: RemotePeerHealth[]): RemotePeerHealth | undefined {
  return healthItems.find((item) => String(item.peer_id || "").trim() === peerId);
}

function taskSummary(task: LocalTaskItem): string {
  if (task.semantics?.summary) return task.semantics.summary;
  if (task.semantics?.title) return task.semantics.title;
  if (typeof task.payload?.input === "string" && task.payload.input.trim()) return task.payload.input.trim();
  if (typeof task.payload?.input === "object" && task.payload.input) {
    for (const key of ["prompt", "content", "text", "query", "instruction"] as const) {
      const value = task.payload.input[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  if (typeof task.payload?._runtime?.prompt === "string" && task.payload._runtime.prompt.trim()) {
    return task.payload._runtime.prompt.trim();
  }
  return task.kind || task.id;
}

function taskOptionLabel(task: LocalTaskItem): string {
  return `${task.id.slice(0, 8)} / ${(task.status || "unknown").toUpperCase()} / ${taskSummary(task).slice(0, 48)}`;
}

const ACP_SESSION_ID_KEYS = ["server_session_id", "serverSessionId", "session_id", "sessionId"] as const;
const ACP_RESULT_TEXT_KEYS = ["output_text", "text", "assistant_message", "message", "content", "response"] as const;
const ACP_PREVIEW_LIMIT = 320;
const MAX_MULTIMODAL_FILES = 6;
const MAX_MULTIMODAL_FILE_BYTES = 4 * 1024 * 1024;

function truncatePreview(value: string, limit: number = ACP_PREVIEW_LIMIT): string {
  const trimmed = value.trim();
  if (trimmed.length <= limit) return trimmed;
  return `${trimmed.slice(0, limit)}...`;
}

function formatByteSize(value: number | undefined): string {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function multimodalKindFromMime(mimeType: string, name?: string): string {
  const normalizedMimeType = String(mimeType || "").trim().toLowerCase();
  const normalizedName = String(name || "").trim().toLowerCase();

  if (normalizedMimeType.startsWith("image/")) return "image";
  if (normalizedMimeType.startsWith("audio/")) return "audio";
  if (normalizedMimeType.startsWith("video/")) return "video";
  if (
    normalizedMimeType.startsWith("text/") ||
    normalizedMimeType.includes("json") ||
    normalizedMimeType.includes("xml") ||
    normalizedMimeType.includes("yaml") ||
    normalizedMimeType.includes("markdown") ||
    /\.(txt|md|json|ya?ml|xml|csv|log)$/i.test(normalizedName)
  ) {
    return "text";
  }
  if (normalizedMimeType === "application/pdf") return "document";
  return "binary";
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("file-read-failed"));
    reader.readAsDataURL(file);
  });
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("file-read-failed"));
    reader.readAsText(file);
  });
}

function extractNestedSessionId(value: unknown, depth: number = 0, seen?: WeakSet<object>): string {
  if (depth > 8 || value == null) return "";
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = extractNestedSessionId(item, depth + 1, seen);
      if (match) return match;
    }
    return "";
  }
  if (typeof value !== "object") return "";

  const nextSeen = seen || new WeakSet<object>();
  if (nextSeen.has(value)) return "";
  nextSeen.add(value);

  const record = value as Record<string, unknown>;
  for (const key of ACP_SESSION_ID_KEYS) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }

  for (const candidate of Object.values(record)) {
    const match = extractNestedSessionId(candidate, depth + 1, nextSeen);
    if (match) return match;
  }

  return "";
}

function inferAcpServerSessionId(session: LocalAcpSession): string {
  return (
    session.last_task_request_intent?.server_session_id?.trim() ||
    extractNestedSessionId(session.initialize_response_frame?.parsed) ||
    extractNestedSessionId(session.latest_task_response_frame?.parsed) ||
    extractNestedSessionId(session.task_response_frame?.parsed) ||
    extractNestedSessionId(session.latest_server_frame?.parsed) ||
    ""
  );
}

function extractTaskResultText(value: unknown, depth: number = 0, seen?: WeakSet<object>): string {
  if (depth > 8 || value == null) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = extractTaskResultText(item, depth + 1, seen);
      if (match) return match;
    }
    return "";
  }
  if (typeof value !== "object") return "";

  const nextSeen = seen || new WeakSet<object>();
  if (nextSeen.has(value)) return "";
  nextSeen.add(value);

  const record = value as Record<string, unknown>;
  for (const key of ACP_RESULT_TEXT_KEYS) {
    const match = extractTaskResultText(record[key], depth + 1, nextSeen);
    if (match) return match;
  }

  for (const candidate of Object.values(record)) {
    const match = extractTaskResultText(candidate, depth + 1, nextSeen);
    if (match) return match;
  }

  return "";
}

function taskResultPreview(task?: LocalTaskItem): string {
  if (!task?.result) return "";

  const extractedText = extractTaskResultText(task.result);
  if (extractedText) return truncatePreview(extractedText);

  try {
    const serialized = JSON.stringify(task.result);
    return truncatePreview(serialized, 240);
  } catch {
    return "";
  }
}

function taskForId(taskId: string, tasks: LocalTaskItem[]): LocalTaskItem | undefined {
  return tasks.find((task) => task.id === taskId);
}

function taskInputAttachments(task?: LocalTaskItem): unknown[] {
  if (!task?.payload) return [];
  if (Array.isArray(task.payload.attachments)) return task.payload.attachments;

  const inputValue = task.payload.input;
  if (inputValue && typeof inputValue === "object" && Array.isArray((inputValue as { attachments?: unknown[] }).attachments)) {
    return (inputValue as { attachments?: unknown[] }).attachments || [];
  }

  return [];
}

function collectTaskMediaAssets(
  value: unknown,
  source: string,
  path: string = source,
  depth: number = 0,
  seen?: WeakSet<object>,
): TaskMediaAsset[] {
  if (depth > 8 || value == null) return [];

  if (Array.isArray(value)) {
    return value.flatMap((item, index) => collectTaskMediaAssets(item, source, `${path}.${index + 1}`, depth + 1, seen));
  }

  if (typeof value !== "object") return [];

  const nextSeen = seen || new WeakSet<object>();
  if (nextSeen.has(value)) return [];
  nextSeen.add(value);

  const record = value as Record<string, unknown>;
  const label = String(record.name || record.filename || record.label || path).trim() || path;
  const mimeType = String(record.mime_type || record.mimeType || record.content_type || record.media_type || "application/octet-stream").trim();
  const kind = multimodalKindFromMime(mimeType, label);
  const dataUrl = String(record.data_url || record.dataUrl || record.url || "").trim();
  const textValue = typeof record.text === "string"
    ? record.text
    : typeof record.content === "string" && !dataUrl
      ? record.content
      : typeof record.output_text === "string"
        ? record.output_text
        : "";
  const size = Number(record.size || record.bytes || 0) || undefined;

  const looksLikeRenderableAsset =
    (dataUrl.startsWith("data:") && Boolean(mimeType)) ||
    (Boolean(textValue.trim()) && (kind === "text" || mimeType.startsWith("text/")));

  if (looksLikeRenderableAsset) {
    return [
      {
        id: `${source}:${path}`,
        label,
        mimeType,
        kind,
        source,
        size,
        dataUrl: dataUrl.startsWith("data:") ? dataUrl : undefined,
        text: textValue.trim() ? truncatePreview(textValue, 1600) : undefined,
      },
    ];
  }

  return Object.entries(record).flatMap(([key, candidate]) =>
    collectTaskMediaAssets(candidate, source, `${path}.${key}`, depth + 1, nextSeen),
  );
}

function dedupeTaskMediaAssets(items: TaskMediaAsset[]): TaskMediaAsset[] {
  const seen = new Set<string>();
  const uniqueItems: TaskMediaAsset[] = [];

  for (const item of items) {
    const fingerprint = [
      item.kind,
      item.mimeType,
      item.label,
      item.dataUrl || "",
      item.text || "",
      item.size != null ? String(item.size) : "",
    ].join("::");

    if (seen.has(fingerprint)) continue;
    seen.add(fingerprint);
    uniqueItems.push(item);
  }

  return uniqueItems;
}

function taskInputAssets(task?: LocalTaskItem): TaskMediaAsset[] {
  return dedupeTaskMediaAssets(collectTaskMediaAssets(taskInputAttachments(task), "input-attachments"));
}

function taskOutputAssets(task?: LocalTaskItem): TaskMediaAsset[] {
  if (!task?.result || typeof task.result !== "object") return [];

  const result = task.result as Record<string, unknown>;
  return dedupeTaskMediaAssets([
    ...collectTaskMediaAssets(result.output_attachments, "result-output-attachments"),
    ...collectTaskMediaAssets(result.artifacts, "result-artifacts"),
    ...collectTaskMediaAssets(result.execution_receipt, "execution-receipt"),
    ...collectTaskMediaAssets(result.runtime_execution, "runtime-execution"),
  ]);
}

function taskMetaSummary(task?: LocalTaskItem): string {
  if (!task) return "";

  const parts = [task.kind, task.role].filter((item) => typeof item === "string" && item.trim());
  if (parts.length > 0) return parts.join(" / ");
  return task.id.slice(0, 12);
}

function acpSessionUpdatedAt(session: LocalAcpSession): string {
  return (
    session.summary?.latest_server_frame_received_at ||
    session.updated_at ||
    session.opened_at ||
    "-"
  );
}

function acpPendingRequestSummary(session: LocalAcpSession): string {
  const requestIds = session.summary?.pending_request_ids || [];
  if (requestIds.length === 0) return "-";
  return requestIds.slice(0, 3).join(" / ");
}

function acpFrameText(frame?: LocalAcpFrame): string {
  const items = frame?.parsed?.result?.content || [];
  const texts = items
    .filter((item) => String(item.type || "").trim().toLowerCase() === "text")
    .map((item) => String(item.text || "").trim())
    .filter(Boolean);
  if (texts.length > 0) return texts.join("\n");
  return String(frame?.raw || "").trim();
}

function managedRegistrationForDiscovery(
  discoveredId: string,
  registrations: LocalManagedRegistration[],
): LocalManagedRegistration | undefined {
  return registrations.find((item) => String(item.discovered_id || "").trim() === discoveredId);
}

function acpSessionForRegistration(
  registrationId: string,
  sessions: LocalAcpSession[],
): LocalAcpSession | undefined {
  return sessions.find(
    (item) => String(item.registration_id || "").trim() === registrationId && String(item.status || "") !== "closed",
  );
}

function renderRadarSweep(
  angle: number,
  foundIds: string[],
  targets: LocalAgentTarget[] = DEFAULT_RADAR_TARGETS,
): string {
  const W = 40, H = 20; 
  const CX = 20, CY = 10;
  const radius = 9.5;
  const buf = new Array(W * H).fill(' ');

  for (let i = 0; i < 360; i++) {
    const rad = (i * Math.PI) / 180;
    const x = Math.round(CX + Math.cos(rad) * radius * 2);
    const y = Math.round(CY + Math.sin(rad) * radius);
    if (x >= 0 && x < W && y >= 0 && y < H) {
      if (typeof buf[y * W + x] !== 'undefined') buf[y * W + x] = '.';
    }
  }

  for (let r = 0; r <= radius; r += 0.5) {
    const x = Math.round(CX + Math.cos(angle) * r * 2);
    const y = Math.round(CY + Math.sin(angle) * r);
    if (x >= 0 && x < W && y >= 0 && y < H) {
      buf[y * W + x] = 'x';
    }
    const trailAngle = angle - 0.15;
    const tx = Math.round(CX + Math.cos(trailAngle) * r * 2);
    const ty = Math.round(CY + Math.sin(trailAngle) * r);
    if (tx >= 0 && tx < W && ty >= 0 && ty < H && buf[ty * W + tx] === ' ') {
      buf[ty * W + tx] = '-';
    }
  }

  targets.forEach(agent => {
    if (foundIds.includes(agent.id)) {
      const ax = Math.round(CX + agent.x);
      const ay = Math.round(CY + agent.y);
      if (ax >= 0 && ax < W && ay >= 0 && ay < H) {
        buf[ay * W + ax] = '@';
        const label = agent.name.substring(0, 3).toUpperCase();
        for (let i = 0; i < label.length; i++) {
           if (ax + 1 + i < W) buf[ay * W + (ax + 1 + i)] = label[i];
        }
      }
    }
  });

  buf[CY * W + CX] = '+';

  const lines: string[] = [];
  for (let r = 0; r < H; r++) lines.push(buf.slice(r * W, (r + 1) * W).join(''));
  return lines.join('\n');
}

const AnatomicalHeart = ({ isOnline }: { isOnline: boolean }) => {
  const matrix = [
    "0000110011000000",
    "0011110011001110",
    "0001110011011010",
    "0011111111111110",
    "0111111111111011",
    "1111111110111111",
    "1111111110111111",
    "1111111111111110",
    "1111111111111110",
    "1111111111011100",
    "0111111111011100",
    "0111111111111100",
    "0011111101111000",
    "0001111100111000",
    "0001111100110000",
    "0000111100110000",
    "0000011110110000",
    "0000001111100000",
    "0000000111000000"
  ];
  return (
    <div className={`flex flex-col ${isOnline ? 'animate-[pulse_1s_ease-in-out_infinite]' : 'opacity-40 grayscale'} mr-1`}>
      {matrix.map((row, i) => (
        <div key={i} className="flex">
          {row.split('').map((cell, j) => (
            <div key={j} className={`w-[2px] h-[2px] sm:w-[3px] sm:h-[3px] ${cell === '1' ? 'bg-red-500' : 'bg-transparent'}`}></div>
          ))}
        </div>
      ))}
    </div>
  );
};

const TaskMediaGallery = ({
  title,
  assets,
  emptyLabel,
  downloadLabel,
}: {
  title: string;
  assets: TaskMediaAsset[];
  emptyLabel: string;
  downloadLabel: string;
}) => {
  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{title}</div>
      {assets.length > 0 ? (
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
          {assets.map((asset) => (
            <div key={asset.id} className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-bold">{asset.label}</div>
                  <div className="opacity-60 break-all">{asset.mimeType}</div>
                  <div className="opacity-50 uppercase tracking-[0.14em]">{asset.source}{asset.size ? ` / ${formatByteSize(asset.size)}` : ""}</div>
                </div>
                {asset.dataUrl && (
                  <a href={asset.dataUrl} download={asset.label} className="shrink-0 underline opacity-80 hover:opacity-100">
                    {downloadLabel}
                  </a>
                )}
              </div>

              {asset.kind === "image" && asset.dataUrl && (
                <img src={asset.dataUrl} alt={asset.label} className="max-h-40 w-full rounded-sm border border-foreground/10 bg-black/30 object-contain" />
              )}
              {asset.kind === "audio" && asset.dataUrl && (
                <audio controls className="w-full">
                  <source src={asset.dataUrl} type={asset.mimeType} />
                </audio>
              )}
              {asset.kind === "video" && asset.dataUrl && (
                <video controls className="max-h-48 w-full rounded-sm border border-foreground/10 bg-black/30">
                  <source src={asset.dataUrl} type={asset.mimeType} />
                </video>
              )}
              {asset.kind === "text" && asset.text && (
                <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-foreground/10 bg-black/30 p-2">{asset.text}</pre>
              )}
              {(asset.kind === "document" || asset.kind === "binary") && asset.dataUrl && (
                <div className="rounded-sm border border-foreground/10 bg-black/30 p-2 opacity-75">{asset.mimeType}</div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal opacity-70">{emptyLabel}</div>
      )}
    </div>
  );
};

export default function TerminalView() {
  const t = useTranslations("Index");
  const tWork = useTranslations("Workspace");
  const tCmd = useTranslations("Commands");
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();

  const [showLanding, setShowLanding] = useState(true);
  const [landingStep, setLandingStep] = useState(0);
  const [typedVision, setTypedVision] = useState("");
  const landingTitle = tWork("landing_overview_title");
  const landingHeader = tWork("landing_header_label");
  const landingBody = tWork("landing_overview_text");
  const landingText = [landingTitle, "", landingBody].join("\n");

  const [history, setHistory] = useState<{type: 'user' | 'system', content: string}[]>([]);
  const [input, setInput] = useState("");
  const [mounted, setMounted] = useState(false);
  const [isOnline, setIsOnline] = useState(false);
  const [mockQueue, setMockQueue] = useState<{id: string, age: number}[]>([]);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [scanComplete, setScanComplete] = useState(false);
  const [isAddingRemote, setIsAddingRemote] = useState(false); // Used for terminal wait mode
  const [isAddingRemotePanel, setIsAddingRemotePanel] = useState(false); // Used for panel visual mode
  const [connectAnimFrame, setConnectAnimFrame] = useState(0);
  const [remoteForm, setRemoteForm] = useState({ endpoint: '', peerId: '', name: ''});
  const [localNodeEndpoint, setLocalNodeEndpoint] = useState("http://127.0.0.1:8080");
  const [localNodeToken, setLocalNodeToken] = useState("");
  const [localNodeBusy, setLocalNodeBusy] = useState(false);
  const [localNodeOnline, setLocalNodeOnline] = useState(false);
  const [localNodeError, setLocalNodeError] = useState("");
  const [localStatus, setLocalStatus] = useState<any>(null);
  const [localManifest, setLocalManifest] = useState<LocalManifest | null>(null);
  const [localChallengeReady, setLocalChallengeReady] = useState(false);
  const [localAttachReady, setLocalAttachReady] = useState(false);
  const [localDiscoveryBusy, setLocalDiscoveryBusy] = useState(false);
  const [localDiscoveryItems, setLocalDiscoveryItems] = useState<LocalDiscoveryItem[]>([]);
  const [remotePeers, setRemotePeers] = useState<RemotePeer[]>([]);
  const [remotePeerCards, setRemotePeerCards] = useState<RemotePeerCard[]>([]);
  const [remotePeerHealth, setRemotePeerHealth] = useState<RemotePeerHealth[]>([]);
  const [remotePeersBusy, setRemotePeersBusy] = useState(false);
  const [remotePeersError, setRemotePeersError] = useState("");
  const [remotePeerSyncBusy, setRemotePeerSyncBusy] = useState(false);
  const [localManagedRegistrations, setLocalManagedRegistrations] = useState<LocalManagedRegistration[]>([]);
  const [localAcpSessions, setLocalAcpSessions] = useState<LocalAcpSession[]>([]);
  const [localAcpBoundary, setLocalAcpBoundary] = useState<LocalAcpBoundary | null>(null);
  const [localTasks, setLocalTasks] = useState<LocalTaskItem[]>([]);
  const [localServices, setLocalServices] = useState<any[]>([]);
  const [localCapabilities, setLocalCapabilities] = useState<any[]>([]);
  const [paymentOpsSummary, setPaymentOpsSummary] = useState<any>(null);
  const [serviceUsageSummary, setServiceUsageSummary] = useState<any>(null);
  const [serviceUsageReconciliation, setServiceUsageReconciliation] = useState<any>(null);
  const [renterTokenSummary, setRenterTokenSummary] = useState<any>(null);
  const [localSessionTaskInputs, setLocalSessionTaskInputs] = useState<Record<string, { taskId: string; serverSessionId: string }>>({});
  const [localRuntimeBusy, setLocalRuntimeBusy] = useState(false);
  const [localRuntimeError, setLocalRuntimeError] = useState("");
  const [localActionBusyKey, setLocalActionBusyKey] = useState("");
  const [localMultimodalPrompt, setLocalMultimodalPrompt] = useState("");
  const [localMultimodalKind, setLocalMultimodalKind] = useState("generic");
  const [localMultimodalAttachments, setLocalMultimodalAttachments] = useState<LocalTaskAttachment[]>([]);
  const [localMultimodalError, setLocalMultimodalError] = useState("");
  const [localMultimodalNotice, setLocalMultimodalNotice] = useState("");
  const [showWorkflowModal, setShowWorkflowModal] = useState(false);

  const asciiCanvasRef = useRef<HTMLCanvasElement>(null);
  const earthAngleRef = useRef(0);
  const [earthDisplay, setEarthDisplay] = useState('');
  const radarAngleRef = useRef(0);
  const [radarDisplay, setRadarDisplay] = useState('');
  const [foundAgents, setFoundAgents] = useState<string[]>([]);
  const [checkedToJoin, setCheckedToJoin] = useState<string[]>([]);
  const [agents, setAgents] = useState<any[]>([
    { 
      name: "GitHub Copilot", 
      icon: (
        <div className="flex flex-col items-center justify-center font-bold tracking-tighter bg-[#0D1117] rounded-sm shadow-inner" style={{width: "60px", height: "60px"}}>
           <div className="flex w-full justify-between px-2">
              <div className="w-[18px] h-[18px] border-2 border-[#5FEADB] rounded-md"></div>
              <div className="w-[18px] h-[18px] border-2 border-[#5FEADB] rounded-md"></div>
           </div>
           <div className="h-[8px]"></div>
           <div className="flex w-full justify-between items-end h-[14px] px-2 relative">
             <div className="w-[10px] h-full bg-[#D946EF]"></div>
             <div className="flex gap-[6px] absolute bottom-0.5 left-1/2 -translate-x-1/2">
                <div className="w-[6px] h-[10px] bg-[#22C55E]"></div>
                <div className="w-[6px] h-[10px] bg-[#22C55E]"></div>
             </div>
             <div className="w-[10px] h-full bg-[#D946EF]"></div>
           </div>
           <div className="w-[44px] h-[6px] bg-[#D946EF] mt-[2px]"></div>
        </div>
      ),
      latency: 24, status: "online", accent: "text-[#5FEADB] hover:shadow-[#5FEADB]/50" 
    },
    { 
      name: "Claude Code", 
      icon: (
        <div className="flex flex-col items-center justify-center font-bold tracking-tighter" style={{width: "60px", height: "60px"}}>
          <div className="flex flex-col items-center w-[55px] drop-shadow-sm">
             <div className="w-[35px] h-[5px] bg-[#D97757]"></div>
             <div className="flex w-[35px] h-[5px]">
                <div className="w-[5px] h-full bg-[#D97757]"></div>
                <div className="w-[5px] h-full bg-[#050505]"></div>
                <div className="w-[15px] h-full bg-[#D97757]"></div>
                <div className="w-[5px] h-full bg-[#050505]"></div>
                <div className="w-[5px] h-full bg-[#D97757]"></div>
             </div>
             <div className="w-[55px] h-[5px] bg-[#D97757]"></div>
             <div className="w-[35px] h-[5px] bg-[#D97757]"></div>
             <div className="flex justify-between w-[35px] h-[10px]">
                <div className="w-[5px] h-full bg-[#D97757]"></div>
                <div className="w-[5px] h-full bg-[#D97757]"></div>
                <div className="w-[5px] h-full bg-[#D97757]"></div>
                <div className="w-[5px] h-full bg-[#D97757]"></div>
             </div>
          </div>
        </div>
      ),
      latency: 32, status: "online", accent: "text-[#D97757] hover:shadow-[#D97757]/50" 
    },
    { 
      name: "OpenAI Codex", 
      icon: (
        <div className="flex flex-col items-center justify-center w-[60px] h-[60px]">
          <div className="flex flex-col drop-shadow-sm opacity-90 group-hover:opacity-100 transition-opacity">
            {[
              "0000011111100000",
              "0001111111111000",
              "0011111111111100",
              "0111111111111110",
              "1111111111111111",
              "1100011111111111",
              "1110001111111111",
              "1111000111111111",
              "1110001111111111",
              "1100011100000111",
              "1111111100000111",
              "1111111111111111",
              "0111111111111110",
              "0011111111111100",
              "0001111111111000",
              "0000011111100000"
            ].map((row, i) => (
              <div key={i} className="flex">
                {row.split('').map((cell, j) => (
                  <div key={j} className={`w-[2.5px] h-[2.5px] sm:w-[3px] sm:h-[3px] ${cell === '1' ? 'bg-foreground' : 'bg-transparent'}`}></div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ),
      latency: 18, status: "online", accent: "text-foreground hover:shadow-foreground/50" 
    },
    { 
      name: "openclaw", 
      icon: (
        <div className="flex flex-col items-center justify-center w-[60px] h-[60px]">
          <div className="flex flex-col drop-shadow-sm opacity-90 group-hover:opacity-100 transition-opacity">
            {[
              "0000100000010000",
              "0000010000100000",
              "0000011111100000",
              "0001111111111000",
              "0011122112211100",
              "0111123112311110",
              "0111122112211110",
              "1111111111111111",
              "1111111111111111",
              "0111111111111110",
              "0011111111111100",
              "0011111111111100",
              "0001111111111000",
              "0000111111110000",
              "0000011001100000",
              "0000011001100000"
            ].map((row, i) => (
              <div key={i} className="flex">
                {row.split('').map((cell, j) => (
                  <div key={j} className={`w-[2.5px] h-[2.5px] sm:w-[3px] sm:h-[3px] ${
                    cell === '1' ? 'bg-[#F2576F]' : 
                    cell === '2' ? 'bg-white' : 
                    cell === '3' ? 'bg-[#00A896]' :
                    'bg-transparent'
                  }`}></div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ),
      latency: 18, status: "online", accent: "text-[#F2576F] hover:shadow-[#F2576F]/50" 
    },
  ]);
  const inputRef = useRef<HTMLInputElement>(null);
  const landingScrollRef = useRef<HTMLDivElement>(null);
  
  const startedRun = useRef(false);

  useEffect(() => {
    setMounted(true);
    if (startedRun.current) return;
    startedRun.current = true;

    const sequence: string[] = t.raw("boot_sequence");
    let delay = 0;
    
    sequence.forEach((msg, idx) => {
      delay += Math.random() * 200 + 100;
      setTimeout(() => {
        setHistory((prev) => [...prev, { type: 'system', content: msg }]);
        if (idx === sequence.length - 1) {
          setTimeout(() => setIsOnline(true), 800);
        }
      }, delay);
    });
  }, [t]);

  useEffect(() => {
    if (!mounted) return;

    const canvas = asciiCanvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d', { alpha: false });
    if (!context) return;

    let rafId = 0;
    let beams = createBackdropBeams(window.innerWidth);
    let lastFrame = 0;

    const resizeCanvas = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = window.innerWidth;
      const height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      beams = createBackdropBeams(width);
      drawBackdropScene(context, width, height, performance.now(), beams);
    };

    const frame = (time: number) => {
      if (time - lastFrame >= 16) {
        drawBackdropScene(context, window.innerWidth, window.innerHeight, time, beams);
        lastFrame = time;
      }
      rafId = requestAnimationFrame(frame);
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    rafId = requestAnimationFrame(frame);

    return () => {
      window.removeEventListener('resize', resizeCanvas);
      cancelAnimationFrame(rafId);
    };
  }, [mounted]);

  // Mock relay queue updates when node is online
  useEffect(() => {
    if (!isOnline) return;
    const interval = setInterval(() => {
       if (Math.random() > 0.5) {
         setMockQueue(prev => {
            const next = prev.map(q => ({...q, age: q.age + 1}));
            if (next.length < 3 && Math.random() > 0.3) {
              next.push({ id: `tx_0x${Math.floor(Math.random()*16777215).toString(16)}`, age: 0 });
            }
            if (next.length > 0 && Math.random() > 0.7) {
              next.shift();
            }
            return next;
         });
       }

       setAgents(prev => prev.map(a => ({
         ...a,
         latency: a.status === 'online' ? Math.floor(Math.random() * 40 + 10) : 0
       })));
    }, 2000);
    return () => clearInterval(interval);
  }, [isOnline]);

  useEffect(() => {
    if (!isDiscovering) {
       setScanComplete(false);
       return;
    }
    const scanTargets = buildLocalAgentTargets(localDiscoveryItems);

    setEarthDisplay(renderEarthSphere(earthAngleRef.current));
    setRadarDisplay(renderRadarSweep(radarAngleRef.current, [], scanTargets));
    setFoundAgents([]);
    setCheckedToJoin(scanTargets.map((target) => target.id));

    const interval = setInterval(() => {
      earthAngleRef.current += 0.09;
      setEarthDisplay(renderEarthSphere(earthAngleRef.current));

      radarAngleRef.current = (radarAngleRef.current + 0.15) % (2 * Math.PI);
      
      setFoundAgents(curr => {
         let newFound = [...curr];
         scanTargets.forEach(target => {
            if (!newFound.includes(target.id)) {
               let diff = Math.abs(radarAngleRef.current - target.angle);
               if (diff > Math.PI) diff = 2 * Math.PI - diff;
               if (diff < 0.25) {
                 newFound.push(target.id);
               }
            }
         });
         setRadarDisplay(renderRadarSweep(radarAngleRef.current, newFound, scanTargets));
         return newFound;
      });
    }, 100);
    
    const t = setTimeout(() => {
      setScanComplete(true);
    }, Math.max(3200, 1800 + scanTargets.length * 700));

    return () => {
      clearInterval(interval);
      clearTimeout(t);
    };
  }, [isDiscovering, localDiscoveryItems]);

  useEffect(() => {
    if (!isAddingRemotePanel) return;
    const interval = setInterval(() => {
      setConnectAnimFrame(f => (f + 1) % 24);
    }, 100);
    return () => clearInterval(interval);
  }, [isAddingRemotePanel]);

  // Global click handler to recover terminal focus if clicking on generic UI (like panel backgrounds)
  useEffect(() => {
    const handleGlobalClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest('input, textarea, button, select, label, a')) return;
      
      if (document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        inputRef.current?.focus();
      }
    };
    document.addEventListener('click', handleGlobalClick);
    return () => document.removeEventListener('click', handleGlobalClick);
  }, []);

  useEffect(() => {
    void probeLocalNode();
  }, []);

  useEffect(() => {
    setLocalSessionTaskInputs((prev) => {
      let changed = false;
      const next: Record<string, { taskId: string; serverSessionId: string }> = { ...prev };
      const sessionIds = new Set(localAcpSessions.map((session) => session.session_id));

      for (const sessionId of Object.keys(next)) {
        if (!sessionIds.has(sessionId)) {
          delete next[sessionId];
          changed = true;
        }
      }

      for (const session of localAcpSessions) {
        const existing = prev[session.session_id];
        const nextTaskId = existing?.taskId?.trim() || session.last_task_request_intent?.mapping?.agentcoin_task_id || "";
        const nextServerSessionId =
          existing?.serverSessionId?.trim() ||
          session.last_task_request_intent?.server_session_id?.trim() ||
          inferAcpServerSessionId(session);

        if (!existing || existing.taskId !== nextTaskId || existing.serverSessionId !== nextServerSessionId) {
          next[session.session_id] = {
            taskId: nextTaskId,
            serverSessionId: nextServerSessionId,
          };
          changed = true;
        }
      }

      return changed ? next : prev;
    });
  }, [localAcpSessions]);

  const renderConnectAnimation = () => {
    const width = 16;
    const isReturning = connectAnimFrame >= width;
    const pos = isReturning ? (width * 2 - connectAnimFrame - 1) : connectAnimFrame;
    let track = "";
    for (let i = 0; i < width; i++) {
        if (i === pos) {
           track += isReturning ? "<" : ">";
        } else {
           track += "-";
        }
    }
    return `[LOCAL] ${track} [REMOTE]`;
  };

  async function probeLocalNode(overrideEndpoint?: string) {
    const baseUrl = normalizeNodeEndpoint(overrideEndpoint ?? localNodeEndpoint);
    if (!baseUrl) return;

    setLocalNodeBusy(true);
    setLocalNodeError("");

    try {
      const statusResponse = await fetchLocalNode(baseUrl, "/v1/status");

      if (!statusResponse.ok) {
        throw new Error(await readLocalNodeFailure(statusResponse, tWork("local_node_unavailable")));
      }

      const statusPayload = await statusResponse.json();

      const [manifestResponse, challengeResponse] = await Promise.all([
        fetchLocalNode(baseUrl, "/v1/manifest"),
        fetchLocalNode(baseUrl, "/v1/auth/challenge"),
      ]);

      const manifest = manifestResponse.ok ? ((await manifestResponse.json()) as LocalManifest) : null;

      setLocalNodeOnline(true);
      setLocalStatus(statusPayload);
      setLocalManifest(manifest);
      setLocalChallengeReady(challengeResponse.ok);
    } catch (error) {
      setLocalNodeOnline(false);
      setLocalStatus(null);
      setLocalManifest(null);
      setLocalChallengeReady(false);
      setLocalAttachReady(false);
      setLocalDiscoveryItems([]);
      setLocalManagedRegistrations([]);
      setLocalAcpSessions([]);
      setLocalAcpBoundary(null);
      setLocalTasks([]);
      setLocalSessionTaskInputs({});
      setLocalRuntimeError("");
      setLocalNodeError(error instanceof Error ? error.message : tWork("local_node_unavailable"));
    } finally {
      setLocalNodeBusy(false);
    }
  }

  async function fetchLocalDiscoveryItems(token: string): Promise<LocalDiscoveryItem[]> {
    const response = await fetchLocalNode(localNodeEndpoint, "/v1/discovery/local-agents", {
      headers: buildAuthHeaders(token),
    });

    if (!response.ok) {
      throw new Error(await readLocalNodeFailure(response, tWork("local_node_discovery_failed")));
    }

    const payload = await response.json();
    return Array.isArray(payload?.items) ? payload.items : [];
  }

  async function fetchRemotePeerState(token: string) {
    const headers = buildAuthHeaders(token);
    const [peersResponse, cardsResponse, healthResponse] = await Promise.all([
      fetchLocalNode(localNodeEndpoint, "/v1/peers", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/peer-cards", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/peer-health?limit=200", { headers }),
    ]);

    if (!peersResponse.ok || !cardsResponse.ok || !healthResponse.ok) {
      const firstFailure = !peersResponse.ok ? peersResponse : !cardsResponse.ok ? cardsResponse : healthResponse;
      throw new Error(await readLocalNodeFailure(firstFailure, tWork("remote_peers_error")));
    }

    const peersPayload = await peersResponse.json();
    const cardsPayload = await cardsResponse.json();
    const healthPayload = await healthResponse.json();

    setRemotePeers(Array.isArray(peersPayload?.items) ? peersPayload.items : []);
    setRemotePeerCards(Array.isArray(cardsPayload?.items) ? cardsPayload.items : []);
    setRemotePeerHealth(Array.isArray(healthPayload?.items) ? healthPayload.items : []);
  }

  async function fetchLocalAgentRuntimeState(token: string) {
    const headers = buildAuthHeaders(token);
    const [managedResponse, acpResponse, tasksResponse] = await Promise.all([
      fetchLocalNode(localNodeEndpoint, "/v1/discovery/local-agents/managed", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/discovery/local-agents/acp-sessions", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/tasks", { headers: { Accept: "application/json" } }),
    ]);

    if (!managedResponse.ok || !acpResponse.ok) {
      const firstFailure = !managedResponse.ok ? managedResponse : acpResponse;
      throw new Error(await readLocalNodeFailure(firstFailure, tWork("local_runtime_error")));
    }

    const managedPayload = await managedResponse.json();
    const acpPayload = await acpResponse.json();

    setLocalManagedRegistrations(Array.isArray(managedPayload?.items) ? managedPayload.items : []);
    setLocalAcpSessions(Array.isArray(acpPayload?.items) ? acpPayload.items : []);
    setLocalAcpBoundary(acpPayload?.protocol_boundary ? acpPayload.protocol_boundary : null);
    if (tasksResponse.ok) {
      const tasksPayload = await tasksResponse.json();
      setLocalTasks(Array.isArray(tasksPayload?.items) ? tasksPayload.items : []);
    } else {
      setLocalTasks([]);
    }
  }

  async function refreshLocalRuntimeState() {
    if (!localNodeOnline) {
      setLocalRuntimeError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setLocalRuntimeError(tWork("local_node_auth_needed"));
      return;
    }

    setLocalRuntimeBusy(true);
    setLocalRuntimeError("");

    try {
      await fetchLocalAgentRuntimeState(localNodeToken);
    } catch {
      setLocalRuntimeError(tWork("local_runtime_error"));
    } finally {
      setLocalRuntimeBusy(false);
    }
  }

  async function postLocalAction(path: string, payload: Record<string, unknown>) {
    const response = await fetchLocalNode(localNodeEndpoint, path, {
      method: "POST",
      headers: {
        ...buildAuthHeaders(localNodeToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(await readLocalNodeFailure(response, "local-action-failed"));
    }

    return response.json();
  }

  async function handleRegisterDiscoveredAgent(item: LocalDiscoveryItem) {
    if (!localNodeToken.trim()) {
      setLocalRuntimeError(tWork("local_node_auth_needed"));
      return;
    }

    setLocalActionBusyKey(`register:${item.id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/register", { discovered_id: item.id });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_register_success", { name: item.title }) }]);
    } catch {
      setLocalRuntimeError(tWork("local_register_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_register_failed") }]);
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleRegisterSelectedAgents() {
    if (!localNodeToken.trim()) {
      setLocalRuntimeError(tWork("local_node_auth_needed"));
      return;
    }

    const selectedItems = localDiscoveryItems.filter(
      (item) => checkedToJoin.includes(item.id) && !managedRegistrationForDiscovery(item.id, localManagedRegistrations),
    );

    if (selectedItems.length === 0) {
      setIsDiscovering(false);
      return;
    }

    setLocalActionBusyKey("register-selected");
    setLocalRuntimeError("");

    try {
      const results = await Promise.allSettled(
        selectedItems.map((item) => postLocalAction("/v1/discovery/local-agents/register", { discovered_id: item.id })),
      );
      const successCount = results.filter((item) => item.status === "fulfilled").length;
      await fetchLocalAgentRuntimeState(localNodeToken);
      setIsDiscovering(false);
      if (successCount > 0) {
        setHistory((prev) => [
          ...prev,
          { type: 'system', content: tWork("local_register_selected_success", { count: successCount }) },
        ]);
      }
      if (successCount !== selectedItems.length) {
        setLocalRuntimeError(tWork("local_register_selected_failed"));
      }
    } catch {
      setLocalRuntimeError(tWork("local_register_selected_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_register_selected_failed") }]);
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleStartRegistration(registration: LocalManagedRegistration) {
    setLocalActionBusyKey(`start:${registration.registration_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/start", { registration_id: registration.registration_id });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_start_success", { name: registration.title || registration.registration_id }) }]);
    } catch {
      setLocalRuntimeError(tWork("local_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleStopRegistration(registration: LocalManagedRegistration) {
    setLocalActionBusyKey(`stop:${registration.registration_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/stop", { registration_id: registration.registration_id });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_stop_success", { name: registration.title || registration.registration_id }) }]);
    } catch {
      setLocalRuntimeError(tWork("local_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleOpenAcpSession(registration: LocalManagedRegistration) {
    setLocalActionBusyKey(`open-acp:${registration.registration_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/open", {
        registration_id: registration.registration_id,
      });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_open_success", { name: registration.title || registration.registration_id }) }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleCloseAcpSession(session: LocalAcpSession) {
    setLocalActionBusyKey(`close-acp:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/close", { session_id: session.session_id });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_close_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleInitializeAcpSession(session: LocalAcpSession) {
    setLocalActionBusyKey(`initialize-acp:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/initialize", {
        session_id: session.session_id,
        dispatch: true,
      });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_initialize_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handlePollAcpSession(session: LocalAcpSession) {
    setLocalActionBusyKey(`poll-acp:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/poll", { session_id: session.session_id });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_poll_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleSendAcpTaskRequest(session: LocalAcpSession) {
    const currentInputs = localSessionTaskInputs[session.session_id] || {
      taskId: session.last_task_request_intent?.mapping?.agentcoin_task_id || "",
      serverSessionId: session.last_task_request_intent?.server_session_id || "",
    };

    if (!currentInputs.taskId.trim() || !currentInputs.serverSessionId.trim()) {
      setLocalRuntimeError(tWork("local_acp_task_fields_required"));
      return;
    }

    setLocalActionBusyKey(`task-request:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/task-request", {
        session_id: session.session_id,
        task_id: currentInputs.taskId.trim(),
        server_session_id: currentInputs.serverSessionId.trim(),
        dispatch: true,
      });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_task_request_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_task_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleApplyAcpTaskResult(session: LocalAcpSession) {
    const currentInputs = localSessionTaskInputs[session.session_id] || {
      taskId: session.last_task_request_intent?.mapping?.agentcoin_task_id || "",
      serverSessionId: session.last_task_request_intent?.server_session_id || "",
    };

    if (!currentInputs.taskId.trim()) {
      setLocalRuntimeError(tWork("local_acp_task_required"));
      return;
    }

    setLocalActionBusyKey(`apply-result:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/apply-task-result", {
        session_id: session.session_id,
        task_id: currentInputs.taskId.trim(),
      });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_apply_result_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_task_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleMultimodalFilesSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";

    if (files.length === 0) return;

    setLocalMultimodalError("");
    setLocalMultimodalNotice("");

    if (localMultimodalAttachments.length + files.length > MAX_MULTIMODAL_FILES) {
      setLocalMultimodalError(
        tWork("local_multimodal_attachment_limit", {
          count: MAX_MULTIMODAL_FILES,
          sizeMb: String(MAX_MULTIMODAL_FILE_BYTES / (1024 * 1024)),
        }),
      );
      return;
    }

    try {
      const nextAttachments = await Promise.all(
        files.map(async (file, index) => {
          if (file.size > MAX_MULTIMODAL_FILE_BYTES) {
            throw new Error(
              tWork("local_multimodal_file_too_large", {
                name: file.name,
                size: formatByteSize(file.size),
              }),
            );
          }

          const mimeType = file.type || "application/octet-stream";
          const kind = multimodalKindFromMime(mimeType, file.name);
          const dataUrl = await readFileAsDataUrl(file);
          const textPreview = kind === "text" ? truncatePreview(await readFileAsText(file), 1200) : undefined;

          return {
            id: `${file.name}-${file.size}-${Date.now()}-${index}`,
            name: file.name,
            mime_type: mimeType,
            kind,
            size: file.size,
            data_url: dataUrl,
            text_preview: textPreview,
          } satisfies LocalTaskAttachment;
        }),
      );

      setLocalMultimodalAttachments((prev) => [...prev, ...nextAttachments]);
    } catch (error) {
      setLocalMultimodalError(error instanceof Error ? error.message : tWork("local_multimodal_dispatch_failed"));
    }
  }

  async function handleDispatchMultimodalTask() {
    if (!localNodeOnline) {
      setLocalMultimodalError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setLocalMultimodalError(tWork("local_node_auth_needed"));
      return;
    }

    const promptText = localMultimodalPrompt.trim();
    if (!promptText && localMultimodalAttachments.length === 0) {
      setLocalMultimodalError(tWork("local_multimodal_dispatch_required"));
      return;
    }

    setLocalActionBusyKey("dispatch-task");
    setLocalMultimodalError("");
    setLocalMultimodalNotice("");
    setLocalRuntimeError("");

    try {
      const attachmentsPayload = localMultimodalAttachments.map((item) => ({
        id: item.id,
        name: item.name,
        mime_type: item.mime_type,
        kind: item.kind,
        size: item.size,
        data_url: item.data_url,
        text_preview: item.text_preview,
      }));

      const response = await fetchLocalNode(localNodeEndpoint, "/v1/tasks/dispatch", {
        method: "POST",
        headers: {
          ...buildAuthHeaders(localNodeToken),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          kind: localMultimodalKind.trim() || "generic",
          role: "worker",
          prefer_local: true,
          payload: {
            input: {
              prompt: promptText,
              attachments: attachmentsPayload,
            },
            attachments: attachmentsPayload,
            _runtime: {
              prompt: promptText,
            },
            multimodal: true,
          },
        }),
      });

      if (!response.ok) {
        throw new Error(await readLocalNodeFailure(response, tWork("local_multimodal_dispatch_failed")));
      }

      const created = await response.json();
      const createdTaskId = String(created?.task?.id || "").trim();

      await fetchLocalAgentRuntimeState(localNodeToken);

      if (createdTaskId && localAcpSessions.length > 0) {
        setLocalSessionTaskInputs((prev) => {
          const next = { ...prev };
          const firstSession = localAcpSessions[0];
          next[firstSession.session_id] = {
            taskId: createdTaskId,
            serverSessionId: prev[firstSession.session_id]?.serverSessionId || inferAcpServerSessionId(firstSession),
          };
          return next;
        });
      }

      setLocalMultimodalPrompt("");
      setLocalMultimodalKind("generic");
      setLocalMultimodalAttachments([]);
      setLocalMultimodalNotice(tWork("local_multimodal_dispatch_success", { id: createdTaskId || "-" }));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_multimodal_dispatch_success", { id: createdTaskId || "-" }) }]);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_multimodal_dispatch_failed");
      setLocalMultimodalError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleRefreshRemotePeers() {
    if (!localNodeOnline) {
      setRemotePeersError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setRemotePeersError(tWork("local_node_auth_needed"));
      return;
    }

    setRemotePeersBusy(true);
    setRemotePeersError("");

    try {
      await fetchRemotePeerState(localNodeToken);
    } catch {
      setRemotePeersError(tWork("remote_peers_error"));
    } finally {
      setRemotePeersBusy(false);
    }
  }

  async function handleSyncRemotePeers() {
    if (!localNodeOnline) {
      setRemotePeersError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setRemotePeersError(tWork("local_node_auth_needed"));
      return;
    }

    setRemotePeerSyncBusy(true);
    setRemotePeersError("");

    try {
      const response = await fetchLocalNode(localNodeEndpoint, "/v1/peers/sync", {
        method: "POST",
        headers: buildAuthHeaders(localNodeToken),
      });
      if (!response.ok) {
        throw new Error(await readLocalNodeFailure(response, tWork("remote_peers_sync_failed")));
      }
      await fetchRemotePeerState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("remote_peers_sync_success") }]);
    } catch {
      setRemotePeersError(tWork("remote_peers_sync_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("remote_peers_sync_failed") }]);
    } finally {
      setRemotePeerSyncBusy(false);
    }
  }

  async function fetchPaymentAndServiceState(token: string) {
    const headers = buildAuthHeaders(token);
    const [
      servicesResponse,
      capabilitiesResponse,
      paymentOpsResponse,
      serviceUsageResponse,
      serviceReconResponse,
      renterTokenResponse
    ] = await Promise.all([
      fetchLocalNode(localNodeEndpoint, "/v1/services", { headers }).catch(() => ({ ok: false }) as Response),
      fetchLocalNode(localNodeEndpoint, "/v1/capabilities", { headers }).catch(() => ({ ok: false }) as Response),
      fetchLocalNode(localNodeEndpoint, "/v1/payments/ops/summary", { headers }).catch(() => ({ ok: false }) as Response),
      fetchLocalNode(localNodeEndpoint, "/v1/payments/service-usage/summary", { headers }).catch(() => ({ ok: false }) as Response),
      fetchLocalNode(localNodeEndpoint, "/v1/payments/service-usage/reconciliation", { headers }).catch(() => ({ ok: false }) as Response),
      fetchLocalNode(localNodeEndpoint, "/v1/payments/renter-tokens/summary", { headers }).catch(() => ({ ok: false }) as Response),
    ]);

    if (servicesResponse.ok) {
      const data = await (servicesResponse as Response).json();
      setLocalServices(Array.isArray(data) ? data : data.services || []);
    }
    if (capabilitiesResponse.ok) {
      const data = await (capabilitiesResponse as Response).json();
      setLocalCapabilities(Array.isArray(data) ? data : data.capabilities || []);
    }
    if (paymentOpsResponse.ok) setPaymentOpsSummary(await (paymentOpsResponse as Response).json());
    if (serviceUsageResponse.ok) setServiceUsageSummary(await (serviceUsageResponse as Response).json());
    if (serviceReconResponse.ok) setServiceUsageReconciliation(await (serviceReconResponse as Response).json());
    if (renterTokenResponse.ok) setRenterTokenSummary(await (renterTokenResponse as Response).json());
  }

  // ==== 弱网与安全增强核心网关 (Robust & Secure Network Gateway) ====
  async function resilientFetch(url: string, options: RequestInit = {}, retries = 2, timeoutMs = 12000): Promise<Response> {
    let attempt = 0;
    while (attempt <= retries) {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(id);
        
        // 如果是 5xx 服务端或网关错误，在弱网下进行重试缓解
        if (!res.ok && res.status >= 500 && attempt < retries) {
           attempt++;
           await new Promise(r => setTimeout(r, 1000 * attempt)); // 退避重试
           continue;
        }
        return res;
      } catch (err: any) {
        clearTimeout(id);
        const isTimeout = err.name === 'AbortError' || err.message?.includes('timeout');
        if (attempt < retries) {
           attempt++;
           await new Promise(r => setTimeout(r, 1000 * attempt));
           continue;
        }
        if (isTimeout) {
           throw new Error("[Network Timeout] 本地节点连接超时，请检查网络稳定性或节点状态。");
        }
        throw new Error(`[Network Error] 节点连接断开或无法建立安全通道: ${err.message || "未知异常"}`);
      }
    }
    throw new Error("Unreachable network state");
  }

  async function handleVerifyAuth(challengeId: string, principal: string, publicKey: string) {
    if (!challengeId || challengeId.length > 256 || !principal || !publicKey) {
      throw new Error("[Security Validation] 非法的认证负载格式，已拦截。");
    }
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, "/v1/auth/verify"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: challengeId, principal, public_key: publicKey }),
    });
    if (!response.ok) {
       const err = await response.text();
       throw new Error(`[Auth Failed] 身份挑战验证被拒绝 (Code: ${response.status}): ${err.slice(0, 100)}`);
    }
    return await response.json();
  }

  async function handleWorkflowExecute(serviceId: string, inputData: any) {
    if (!serviceId || typeof serviceId !== 'string' || serviceId.length > 128) {
      throw new Error("[Security Validation] 拦截：危险的工作流服务标识格式。");
    }
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, "/v1/workflow/execute"), {
      method: "POST",
      headers: { ...buildAuthHeaders(localNodeToken), "Content-Type": "application/json" },
      body: JSON.stringify({ service_id: serviceId, input: inputData }),
    });
    
    if (response.status === 402) {
      // 标准化处理计费网关的 402 异常
      const paymentRequiredJson = await response.json().catch(() => null);
      const paymentHeader = response.headers.get("X-Agentcoin-Payment-Required") || "";
      let quoteDetails = paymentHeader;
      if (paymentRequiredJson?.payment?.quote) {
         quoteDetails = JSON.stringify(paymentRequiredJson.payment.quote);
      }
      throw new Error(`[Payment Required] 触发智能合约计费拦截。所需支付配置: ${quoteDetails}`);
    } else if (response.status === 401 || response.status === 403) {
      throw new Error(`[Access Denied] 节点拒绝了您的会话凭证，请检查 Auth 身份。`);
    } else if (!response.ok) {
      const errText = await response.text().catch(() => "Unknown");
      throw new Error(`[Execution Error] 节点执行异常 (${response.status}): ${errText.slice(0, 150)}`);
    }
    return await response.json();
  }

  async function handleRenterTokenOperations(action: 'issue' | 'introspect', payload: any) {
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, `/v1/payments/renter-tokens/${action}`), {
      method: "POST",
      headers: { ...buildAuthHeaders(localNodeToken), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
       const errText = await response.text();
       throw new Error(`[Token Error] 租赁令牌操作(${action})失败: ${errText.slice(0, 100)}`);
    }
    return await response.json();
  }

  async function handleReceiptOperations(action: 'issue' | 'introspect', payload: any) {
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, `/v1/payments/receipts/${action}`), {
      method: "POST",
      headers: { ...buildAuthHeaders(localNodeToken), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
       const errText = await response.text();
       throw new Error(`[Receipt Error] 凭证操作(${action})失败: ${errText.slice(0, 100)}`);
    }
    return await response.json();
  }

  async function handleAttachLocalNode() {
    if (!localNodeToken.trim()) {
      setLocalNodeError(tWork("local_node_auth_needed"));
      return;
    }

    setLocalDiscoveryBusy(true);
    setLocalNodeError("");
    setLocalRuntimeError("");

    try {
      const items = await fetchLocalDiscoveryItems(localNodeToken);
      setLocalAttachReady(true);
      setLocalDiscoveryItems(items);
      setCheckedToJoin(items.map((item) => item.id));
      const [remoteStateResult, runtimeStateResult, extendedStateResult] = await Promise.allSettled([
        fetchRemotePeerState(localNodeToken),
        fetchLocalAgentRuntimeState(localNodeToken),
        fetchPaymentAndServiceState(localNodeToken),
      ]);
      if (remoteStateResult.status === "rejected") {
        setRemotePeersError(tWork("remote_peers_error"));
      }
      if (runtimeStateResult.status === "rejected") {
        setLocalRuntimeError(tWork("local_runtime_error"));
      }
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_attach_success") }]);
    } catch {
      setLocalAttachReady(false);
      setLocalNodeError(tWork("local_node_attach_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_attach_failed") }]);
    } finally {
      setLocalDiscoveryBusy(false);
    }
  }

  async function handleDiscoverAgents() {
    setIsAddingRemotePanel(false);

    if (!localNodeOnline) {
      setLocalNodeError(tWork("local_node_unavailable"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_unavailable") }]);
      return;
    }

    if (!localNodeToken.trim()) {
      setLocalNodeError(tWork("local_node_auth_needed"));
      return;
    }

    setLocalDiscoveryBusy(true);
    setLocalNodeError("");
    setLocalRuntimeError("");

    try {
      const items = await fetchLocalDiscoveryItems(localNodeToken);
      setLocalAttachReady(true);
      setLocalDiscoveryItems(items);
      setCheckedToJoin(items.map((item) => item.id));
      const [remoteStateResult, runtimeStateResult, extendedStateResult] = await Promise.allSettled([
        fetchRemotePeerState(localNodeToken),
        fetchLocalAgentRuntimeState(localNodeToken),
        fetchPaymentAndServiceState(localNodeToken),
      ]);
      if (remoteStateResult.status === "rejected") {
        setRemotePeersError(tWork("remote_peers_error"));
      }
      if (runtimeStateResult.status === "rejected") {
        setLocalRuntimeError(tWork("local_runtime_error"));
      }
      setScanComplete(false);
      setIsDiscovering(true);
      setHistory((prev) => [
        ...prev,
        { type: 'system', content: tWork("local_node_discovery_summary", { count: items.length }) },
      ]);
    } catch {
      setIsDiscovering(false);
      setLocalAttachReady(false);
      setLocalNodeError(tWork("local_node_discovery_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_discovery_failed") }]);
    } finally {
      setLocalDiscoveryBusy(false);
    }
  }

  const handleEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && input.trim()) {
      const cmd = input.trim();
      setHistory(prev => [...prev, { type: 'user', content: `host@agentcoin:~$ ${cmd}` }]);
      
      const lowerCmd = cmd.toLowerCase();
      
      const aliasesClear: string[] = tCmd.raw("aliases_clear");
      const aliasesHelp: string[] = tCmd.raw("aliases_help");
      const aliasesPing: string[] = tCmd.raw("aliases_ping");
      const aliasesWhoamI: string[] = tCmd.raw("aliases_whoami");
      const aliasesQueue: string[] = tCmd.raw("aliases_queue");
      const aliasesServices: string[] = ["services", "ls", "cap", "capabilities"];
      const aliasesPayments: string[] = ["payments", "pay", "ops", "token", "recon"];
      const aliasesWorkflow: string[] = ["workflow", "new", "run", "do"];

      if (aliasesClear.includes(lowerCmd)) {
        setHistory([]);
      } else if (aliasesHelp.includes(lowerCmd)) {
        setHistory(prev => [...prev, { type: 'system', content: tCmd("help") }]);
      } else if (aliasesWorkflow.includes(lowerCmd)) {
        setShowWorkflowModal(true);
        setHistory(prev => [...prev, { type: 'system', content: "[ Initializing visual runtime modal... ]" }]);
      } else if (aliasesPing.includes(lowerCmd)) {
        const ms = Math.floor(Math.random() * 30 + 5);
        setHistory(prev => [...prev, { type: 'system', content: tCmd("ping", { ms }) }]);
      } else if (aliasesWhoamI.includes(lowerCmd)) {
        setHistory(prev => [...prev, { type: 'system', content: tCmd("whoami") }]);
      } else if (aliasesQueue.includes(lowerCmd)) {
        const lines = mockQueue.length === 0 
           ? tWork("empty_queue") 
           : mockQueue.map(q => `[PENDING] ${q.id} (Age: ${q.age}s)`).join('\n');
        setHistory(prev => [...prev, { type: 'system', content: lines }]);
      } else if (aliasesServices.includes(lowerCmd)) {
        if (!localServices.length && !localCapabilities.length) {
           setHistory(prev => [...prev, { type: 'system', content: "[No Services or Capabilities discovered. Did you auth and attach?]" }]);
        } else {
           const lines = [
             "--- DISCOVERED CAPABILITIES ---",
             ...localCapabilities.map((c: any) => `* ${c.id || c.name || 'Unknown'}: ${c.description || ''}`),
             "--- DISCOVERED SERVICES ---",
             ...localServices.map((s: any) => `* [${s.service_id}] ${s.price_per_call || 0} ${s.price_asset || 'CREDIT'}/call`)
           ].join("\n");
           setHistory(prev => [...prev, { type: 'system', content: lines }]);
        }
      } else if (aliasesPayments.includes(lowerCmd)) {
        if (!paymentOpsSummary && !renterTokenSummary) {
           setHistory(prev => [...prev, { type: 'system', content: "[No Payment Ops discovered. Did you auth and attach?]" }]);
        } else {
           const queues = paymentOpsSummary?.queue_summary || {};
           const lines = [
             "--- PAYMENT OPS & QUEUE ---",
             `* Running Relays: ${queues.running || 0}`,
             `* Requeue/Dead: ${queues.requeue || 0} / ${queues.dead_letter || 0}`,
             "--- SERVICE USAGE (RECONCILIATION) ---",
             `* Status: ${serviceUsageReconciliation?.reconciliation_status || 'idle'}`,
             `* Advised Action: ${serviceUsageReconciliation?.recommended_actions?.[0] || 'none'}`,
             "--- RENTER TOKENS ---",
             `* Count: ${renterTokenSummary?.total_tokens || 0}`,
             `* Remaining Aggregate Uses: ${serviceUsageSummary?.total_remaining_uses || 0}`
           ].join("\n");
           setHistory(prev => [...prev, { type: 'system', content: lines }]);
        }
      } else {
        setHistory(prev => [...prev, { type: 'system', content: t("error_unrecognized") }]);
      }
      
      setTimeout(() => {
         const terminalContainer = inputRef.current?.closest('.overflow-y-auto');
         if (terminalContainer) {
            terminalContainer.scrollTop = terminalContainer.scrollHeight;
         }
      }, 50);
      setInput("");
    }
  };

  const switchLanguage = (newLocale: string) => {
    const currentPath = window.location.pathname;
    const newPath = currentPath.replace(`/${locale}`, `/${newLocale}`);
    router.replace(newPath);
  };

  const runningRegistrations = localManagedRegistrations.filter((item) => item.status === "running").length;
  const transportReadySessions = localAcpSessions.filter((item) => item.status === "open").length;
  const totalCapturedFrames = localAcpSessions.reduce((sum, item) => sum + Number(item.server_frames_seen || 0), 0);

  useEffect(() => {
    if (!showLanding) return;

    setLandingStep(0);
    setTypedVision("");

    const timers: ReturnType<typeof setTimeout>[] = [];
    let playback = "";
    let delay = 260;

    const scheduleSnapshot = (snapshot: string, wait: number) => {
      timers.push(setTimeout(() => setTypedVision(snapshot), wait));
    };

    const charDelay = (char: string) => {
      if (char === "\n") return 95;
      if (/[.,!?;:]/.test(char)) return 58;
      if (/[，。！？；：、】【】]/.test(char)) return 70;
      return 20;
    };

    const scheduleChunk = (text: string, stepDelay: number) => {
      for (const char of text) {
        playback += char;
        delay += Math.max(stepDelay, charDelay(char));
        scheduleSnapshot(playback, delay);
      }
    };

    const earthInterval = setInterval(() => {
      earthAngleRef.current -= 0.05;
      setEarthDisplay(renderEarthSphere(earthAngleRef.current));
    }, 50);

    scheduleChunk(landingText, 20);

    timers.push(setTimeout(() => setLandingStep(1), delay + 1800));

    return () => {
      clearInterval(earthInterval);
      timers.forEach(clearTimeout);
    };
  }, [showLanding, landingText]);

  useEffect(() => {
    if (!showLanding) return;
    const container = landingScrollRef.current;
    if (!container) return;

    const frame = requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });

    return () => cancelAnimationFrame(frame);
  }, [typedVision, showLanding, landingStep]);

  const handleLandingContinue = () => {
    if (typeof window !== "undefined" && window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "agentcoin-legacy-landing-complete" }, window.location.origin);
      return;
    }

    setShowLanding(false);
  };

  if (!mounted) return null;

  const asciiBackdropLayer = (
    <div aria-hidden className="pointer-events-none fixed inset-[-4%] z-0 overflow-hidden bg-black">
      <canvas ref={asciiCanvasRef} className="absolute inset-0 h-full w-full opacity-100" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_52%,rgba(255,255,255,0.08),transparent_26%),radial-gradient(circle_at_50%_90%,rgba(255,255,255,0.04),transparent_38%)] opacity-100" />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(0,0,0,0.16),rgba(0,0,0,0.04)_28%,rgba(0,0,0,0.35)_72%,rgba(0,0,0,0.78))]" />
    </div>
  );

  if (showLanding) {
    return (
      <div className="min-h-screen bg-transparent text-white font-mono flex flex-col items-center justify-center overflow-x-hidden selection:bg-white selection:text-black relative z-10 w-full h-[100dvh]">
          {asciiBackdropLayer}
          {/* AgentCoin 覆盖于星球上半部 */}
          <div className="absolute top-0 md:top-[1%] w-full flex justify-center z-20 pointer-events-none">
            <div className="bg-black/94 px-4 py-2 sm:px-6 sm:py-3 shadow-[0_0_28px_rgba(0,0,0,0.95)]">
              <pre className="text-[10px] sm:text-[12px] md:text-[15px] font-bold text-center text-white mix-blend-screen scale-y-90 sm:scale-y-100 drop-shadow-[0_0_18px_rgba(255,255,255,0.75)]" style={{textShadow: "0 0 10px rgba(255,255,255,0.85)"}}>
                {ASCII_ART}
              </pre>
            </div>
          </div>
          
          <div className="relative flex justify-center items-center w-full h-full mt-8 z-10 flex-grow">
            {/* 地球文本采用白色 + 发光特效 */}
            <pre className="translate-y-10 sm:translate-y-14 md:translate-y-20 text-[6.4px] sm:text-[7.9px] md:text-[9.6px] text-center text-white opacity-95 leading-[1.03] sm:leading-[1.06] m-0 pointer-events-none font-bold" style={{textShadow: "0 0 4px rgba(255,255,255,0.85)"}}>
              {earthDisplay || renderEarthSphere(0)}
            </pre>
            
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none mt-24 sm:mt-32 md:mt-40 z-30">
              <div className="relative overflow-hidden bg-black/36 backdrop-blur-md px-3 py-4 sm:px-4 sm:py-5 md:px-5 md:py-6 border border-white/45 w-[min(74vw,760px)] sm:w-[min(72vw,780px)] md:w-[min(68vw,760px)] h-[360px] sm:h-[420px] md:h-[470px] text-center shadow-[0_0_55px_rgba(255,255,255,0.13),inset_0_0_18px_rgba(255,255,255,0.08)] animate-[fade-in_0.5s_ease-out] pointer-events-auto border-t-[1.5px] border-t-white/80 flex flex-col">
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-white/16 via-white/[0.03] to-transparent opacity-90"></div>
                <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/12 to-transparent"></div>
                <div className="pointer-events-none absolute inset-0 opacity-[0.14]" style={{backgroundImage: "repeating-linear-gradient(to bottom, rgba(255,255,255,0.22) 0px, rgba(255,255,255,0.22) 1px, transparent 1px, transparent 6px)"}}></div>
                <div className="pointer-events-none absolute inset-[1px] border border-white/10"></div>
                <div className="relative mb-3 flex items-center justify-between border-b border-white/18 pb-3 text-[10px] tracking-[0.16em] text-white/80 sm:text-[11px]">
                  <span className="font-bold text-white/90">{landingHeader}</span>
                  <span className="text-white/55">agentcoin://manifest</span>
                </div>
                <div ref={landingScrollRef} className="landing-scrollbar relative flex-1 overflow-y-auto overflow-x-hidden pr-1 sm:pr-2 pb-3">
                  <pre className="block w-full text-white text-[10px] sm:text-[11px] md:text-[12px] whitespace-pre-wrap font-bold tracking-[0.015em] leading-[1.78] font-mono m-0 transition-all text-left" style={{ textShadow: "0 0 12px rgba(255,255,255,0.68)"}}>
                    {typedVision}
                    <span className="w-2.5 h-[1em] bg-white inline-block animate-pulse ml-1 align-bottom shadow-[0_0_12px_rgba(255,255,255,1)]"></span>
                  </pre>
                </div>

                <div className="relative mt-4 min-h-[76px] pt-4 border-t border-white/20 flex items-center justify-between gap-4">
                  <div className="text-left text-[9px] uppercase tracking-[0.16em] text-white/45 sm:text-[10px]">
                    <div>scroll://live</div>
                    <div>{landingStep >= 1 ? "status://ready" : "status://reading"}</div>
                  </div>
                  <button 
                    onClick={handleLandingContinue}
                    className={`px-6 py-3 uppercase tracking-widest text-[10px] sm:text-xs font-bold border focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-4 focus:ring-offset-black active:translate-y-1 active:shadow-none transition-all ${landingStep >= 1 ? 'pointer-events-auto bg-white text-black border-white shadow-[0_0_28px_rgba(255,255,255,0.92)] hover:bg-[#f7f7f7]' : 'pointer-events-none bg-white/0 text-white/0 border-white/0 opacity-0 translate-y-2 shadow-none'}`}
                  >
                    {tWork("btn_enter_workspace", { defaultValue: "[ Initialize Workspace ]" })}
                  </button>
                </div>
              </div>
            </div>
          </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-transparent text-foreground font-mono p-4 sm:p-6 selection:bg-foreground selection:text-background transition-colors duration-0 flex flex-col relative z-10">
      {asciiBackdropLayer}
      
      {/* HEADER: Language & Theme Controls (Available Immediately) */}
      <header className="border-b-2 border-foreground pb-4 mb-6 flex justify-between items-end gap-4 flex-wrap shrink-0">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold uppercase tracking-wider">{tWork("title")}</h1>
          <div className="text-sm mt-3 flex items-center gap-2">
            <div className="transform scale-[0.4] origin-left mr-[-8px]"><AnatomicalHeart isOnline={isOnline} /></div>
            {isOnline ? tWork("status_online") : tWork("status_offline")}
          </div>
        </div>
        
        <div className="flex gap-4 text-xs sm:text-sm">
          <div className="flex flex-col gap-1 items-end">
            <span>[{tWork("theme")}]</span>
            <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} className="underline hover:bg-foreground hover:text-background px-1 transition-none uppercase">
              {theme === 'dark' ? tWork("light_mode") : tWork("dark_mode")}
            </button>
          </div>
          
          <div className="flex flex-col gap-1 items-end">
            <span>[{tWork("language")}]</span>
            <div className="flex gap-2">
               <button onClick={() => switchLanguage('en')} className={`${locale === 'en' ? 'bg-foreground text-background' : 'underline hover:bg-foreground hover:text-background'} px-1 transition-none`}>{tWork("lang_en")}</button>
               <button onClick={() => switchLanguage('zh')} className={`${locale === 'zh' ? 'bg-foreground text-background' : 'underline hover:bg-foreground hover:text-background'} px-1 transition-none`}>{tWork("lang_zh")}</button>
               <button onClick={() => switchLanguage('ja')} className={`${locale === 'ja' ? 'bg-foreground text-background' : 'underline hover:bg-foreground hover:text-background'} px-1 transition-none`}>{tWork("lang_ja")}</button>
            </div>
          </div>
        </div>
      </header>

      {/* MAIN: Terminal + Widgets */}
      <main className="flex-grow grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Terminal Area */}
        <div className="lg:col-span-2 flex flex-col border-2 border-foreground bg-muted/5 relative h-[68vh] lg:h-[78vh] p-4 pt-10">
          <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold z-10">
            {tWork("terminal_label")}
          </div>
          
          <div className="overflow-y-auto custom-scrollbar flex-grow pb-4 space-y-1">
            <pre className="text-muted-foreground mb-6 whitespace-pre-wrap leading-tight text-[10px] sm:text-xs md:text-sm">
              {ASCII_ART}
            </pre>
            
            {history.map((msg, i) => (
              <div key={i} className={`${msg.type === 'user' ? 'text-foreground' : 'text-muted-foreground'} whitespace-pre-wrap text-sm sm:text-base`}>
                {msg.type === 'system' ? `> ${msg.content}` : msg.content}
              </div>
            ))}

            {/* Input Row with correctly following block cursor */}
            <div className="flex flex-wrap items-center text-foreground mt-4 relative text-sm sm:text-base">
              <span className="mr-2 shrink-0">host@agentcoin:~$</span>
              
              <div className="relative flex-grow flex items-center min-h-[1.5rem]" onClick={() => inputRef.current?.focus()}>
                {/* Visible typed text */}
                <span className="whitespace-pre break-all">{input}</span>
                {/* Following solid blinking cursor */}
                <span className="w-2.5 h-5 bg-foreground inline-block animate-pulse shrink-0 ml-[1px]"></span>
                
                {/* Invisible input overlay taking focus and keyboard events */}
                <input
                  ref={inputRef}
                  autoFocus
                  className="absolute inset-0 w-full h-full opacity-0 cursor-text bg-transparent outline-none border-none"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleEnter}
                  onBlur={(e) => {
                    const dest = e.relatedTarget as HTMLElement | null;
                    if (dest && ['INPUT', 'TEXTAREA', 'BUTTON', 'SELECT'].includes(dest.tagName)) return;
                    setTimeout(() => {
                      if (document.activeElement?.tagName !== 'INPUT' && inputRef.current) {
                        inputRef.current.focus();
                      }
                    }, 50);
                  }}
                  spellCheck={false}
                  autoComplete="off"
                />
              </div>
            </div>
          </div>
        </div>
        
        {/* Right Panel Workspace Widgets */}
        <div className="flex flex-col gap-6 h-[68vh] lg:h-[78vh]">
          <div className="border-2 border-foreground bg-muted/5 relative flex flex-col p-4 pt-10 h-full">
            <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold flex justify-between w-full items-center z-10">
              <span>{tWork("sys_info_label")}</span>
              <div className="flex gap-4">
                <button 
                  onClick={() => setShowWorkflowModal(true)}
                  className="hover:underline opacity-80 hover:opacity-100"
                >
                  {tWork("btn_new_workflow", { defaultValue: "[ NEW_WORKFLOW ]" })}
                </button>
                <button 
                  onClick={() => {
                     setIsAddingRemotePanel(true);
                     setIsDiscovering(false);
                     void handleRefreshRemotePeers();
                  }}
                  className="hover:underline opacity-80 hover:opacity-100"
                >
                  {tWork("add_remote_agent")}
                </button>
                <button 
                  onClick={() => {
                     void handleDiscoverAgents();
                  }}
                  disabled={isDiscovering || localDiscoveryBusy}
                  className="hover:underline opacity-80 hover:opacity-100 disabled:opacity-50"
                >
                  {tWork("discover_agents")}
                </button>
              </div>
            </div>
            
            <div className="mt-2 text-sm flex-grow overflow-y-auto custom-scrollbar flex flex-col pr-1">
              <div className="p-4 text-left font-mono min-h-[220px] flex-grow relative flex flex-col gap-4">
                <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm animate-[fade-in_0.2s_ease-out]">
                  <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.2em] opacity-80">
                    <span>{tWork("local_node_label")}</span>
                    <button
                      onClick={() => {
                        void probeLocalNode();
                      }}
                      className="hover:underline disabled:opacity-50"
                      disabled={localNodeBusy}
                    >
                      {tWork("local_node_probe")}
                    </button>
                  </div>

                  <div className="mt-3 flex flex-col gap-3">
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="opacity-80">[{tWork("local_node_endpoint")}]</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors"
                        value={localNodeEndpoint}
                        onChange={(e) => setLocalNodeEndpoint(e.target.value)}
                        placeholder="http://127.0.0.1:8080"
                      />
                    </label>

                    <div className="space-y-1.5 text-[10px] sm:text-[11px] uppercase tracking-[0.12em] text-foreground/75">
                      <div>{localNodeBusy ? tWork("local_node_status_checking") : localNodeOnline ? tWork("local_node_status_online") : tWork("local_node_status_offline")}</div>
                      <div>{localAttachReady ? tWork("local_node_auth_ready") : tWork("local_node_auth_needed")}</div>
                      <div>{localManifest?.name || tWork("local_node_manifest_missing")}</div>
                      {localManifest?.auth?.shared_bearer_enabled && <div>{tWork("local_node_shared_bearer")}</div>}
                      {(localChallengeReady || localManifest?.auth?.passwordless) && <div>{tWork("local_node_passwordless")}</div>}
                      {localDiscoveryItems.length > 0 && <div>{tWork("local_node_discovery_summary", { count: localDiscoveryItems.length })}</div>}
                      {localServices.length > 0 && <div>[Services Discovered] {localServices.length}</div>}
                      {localCapabilities.length > 0 && <div>[Capabilities Discovered] {localCapabilities.length}</div>}
                      {paymentOpsSummary && <div>[Payment Ops] Active Relays: {paymentOpsSummary.queue_summary?.running || 0}</div>}
                      {serviceUsageSummary && <div>[Service Usage] Tokens Active: {serviceUsageSummary.active_tokens || 0}, Remaining Uses: {serviceUsageSummary.total_remaining_uses || 0}</div>}
                      {serviceUsageReconciliation && <div>[Reconciliation] Status: {serviceUsageReconciliation.reconciliation_status || 'idle'}, Action: {serviceUsageReconciliation.recommended_actions?.[0] || 'none'}</div>}
                      {renterTokenSummary && <div>[Renter Tokens] Count: {renterTokenSummary.total_tokens || renterTokenSummary.items?.length || 0}</div>}
                      {(localManagedRegistrations.length > 0 || localAcpSessions.length > 0) && (
                        <div>{tWork("local_runtime_summary", { registrations: localManagedRegistrations.length, sessions: localAcpSessions.length })}</div>
                      )}
                      {localNodeError && <div className="text-red-400 normal-case tracking-normal">{localNodeError}</div>}
                      {localRuntimeError && <div className="text-red-400 normal-case tracking-normal">{localRuntimeError}</div>}
                    </div>

                    <label className="flex flex-col gap-1 text-xs">
                      <span className="opacity-80">[{tWork("local_node_token")}]</span>
                      <input
                        type="password"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors"
                        value={localNodeToken}
                        onChange={(e) => setLocalNodeToken(e.target.value)}
                        placeholder={tWork("local_node_token_placeholder")}
                      />
                    </label>

                    <div className="flex justify-end gap-3">
                      <button
                        className="hover:underline opacity-80 hover:opacity-100 text-xs disabled:opacity-50"
                        onClick={() => {
                          void probeLocalNode();
                        }}
                        disabled={localNodeBusy}
                      >
                        {tWork("local_node_probe")}
                      </button>
                      <button
                        className="bg-foreground text-background font-bold px-4 py-1 hover:opacity-80 transition-opacity text-xs disabled:opacity-50"
                        onClick={() => {
                          void handleAttachLocalNode();
                        }}
                        disabled={!localNodeOnline || !localNodeToken.trim() || localDiscoveryBusy}
                      >
                        {tWork("local_node_attach")}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="flex-grow relative flex flex-col">
                  {isAddingRemotePanel ? (
                    <div className="flex flex-col w-full h-full animate-[fade-in_0.3s_ease-out]">
                      <div className="flex justify-center my-6">
                        <pre className="text-foreground font-bold tracking-widest text-xs sm:text-sm whitespace-pre">
                          {renderConnectAnimation()}
                        </pre>
                      </div>

                      <div className="flex flex-col gap-4 mt-2 flex-grow">
                        <div className="border border-foreground/20 bg-foreground/5 p-3 text-[10px] sm:text-[11px] uppercase tracking-[0.14em] space-y-2 opacity-80">
                          <div>{tWork("remote_peers_label")}</div>
                          <div>{tWork("remote_peers_summary", { peers: remotePeers.length, cards: remotePeerCards.length, health: remotePeerHealth.length })}</div>
                          <div className="normal-case tracking-normal opacity-70">{tWork("remote_peers_config_hint")}</div>
                          {remotePeersError && <div className="text-red-400 normal-case tracking-normal">{remotePeersError}</div>}
                        </div>

                        <div className="space-y-3 flex-grow overflow-y-auto custom-scrollbar pr-1">
                          {remotePeers.map((peer) => {
                            const card = remotePeerCardFor(peer.peer_id, remotePeerCards);
                            const health = remotePeerHealthFor(peer.peer_id, remotePeerHealth);
                            const healthState = health?.blacklisted_until
                              ? tWork("remote_peers_blacklisted")
                              : health?.cooldown_until
                                ? tWork("remote_peers_cooldown")
                                : card
                                  ? tWork("remote_peers_card_ready")
                                  : tWork("remote_peers_card_missing");
                            const trustState = card?.identity_trust?.requires_review
                              ? tWork("remote_peers_trust_review")
                              : card?.identity_trust?.aligned
                                ? tWork("remote_peers_trust_aligned")
                                : tWork("remote_peers_trust_unknown");

                            return (
                              <div key={peer.peer_id} className="flex justify-between items-start gap-4 bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm animate-[fade-in_0.2s_ease-out]">
                                <div className="min-w-0 flex items-start gap-3">
                                  <div className="w-10 h-10 shrink-0 border border-foreground/30 bg-black/50 flex items-center justify-center text-[11px] font-bold tracking-[0.18em]">
                                    {peer.peer_id.slice(0, 3).toUpperCase()}
                                  </div>
                                  <div className="min-w-0 space-y-1">
                                    <div className="text-sm font-bold truncate">{peer.name || peer.peer_id}</div>
                                    <div className="text-[10px] opacity-70 truncate uppercase tracking-widest">{peer.overlay_endpoint || peer.url || peer.peer_id}</div>
                                    {card?.card?.description && <div className="text-[10px] opacity-65 truncate">{card.card.description}</div>}
                                    {health?.last_error && <div className="text-[10px] text-red-400 truncate">{health.last_error}</div>}
                                  </div>
                                </div>
                                <div className="shrink-0 text-right text-[10px] uppercase tracking-widest space-y-1 opacity-80 max-w-[132px]">
                                  <div>{healthState}</div>
                                  <div>{trustState}</div>
                                  <div>{card?.card?.protocols?.slice(0, 2).join(" / ") || tWork("remote_peers_no_protocols")}</div>
                                </div>
                              </div>
                            );
                          })}

                          {!remotePeersBusy && remotePeers.length === 0 && (
                            <div className="border border-foreground/20 bg-foreground/5 p-4 text-xs opacity-80 uppercase tracking-widest text-center">
                              {tWork("remote_peers_empty")}
                            </div>
                          )}
                        </div>

                        <div className="flex justify-end gap-4 mt-2 border-t border-foreground/10 pt-4">
                          <button
                            className="hover:underline opacity-80 hover:opacity-100 text-xs disabled:opacity-50 mr-auto"
                            onClick={() => {
                              void handleRefreshRemotePeers();
                            }}
                            disabled={remotePeersBusy}
                          >
                            {tWork("remote_peers_refresh")}
                          </button>
                          <button 
                            className="hover:underline opacity-70 hover:opacity-100 text-xs"
                            onClick={() => {
                               setIsAddingRemotePanel(false);
                               setTimeout(() => inputRef.current?.focus(), 50);
                            }}
                          >
                            {tWork("btn_cancel")}
                          </button>
                          <button 
                            className="bg-foreground text-background font-bold px-4 py-1 hover:opacity-80 transition-opacity text-xs disabled:opacity-50"
                            onClick={() => {
                              void handleSyncRemotePeers();
                            }}
                            disabled={!localNodeToken.trim() || remotePeerSyncBusy}
                          >
                            {tWork("remote_peers_sync")}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : isDiscovering ? (
                    <div className="flex flex-col items-center justify-start bg-transparent w-full flex-grow">
                      <pre 
                        className="text-green-500 font-mono whitespace-pre font-bold" 
                        style={{ 
                          fontSize: '9px', 
                          lineHeight: '9px',
                        }}
                      >
                        {radarDisplay}
                      </pre>
                      <div className="text-[10px] sm:text-xs uppercase tracking-widest opacity-80 text-center w-full mt-4 mb-4 shrink-0">
                        {scanComplete 
                           ? tWork("radar_complete", { found: foundAgents.length, total: localDiscoveryItems.length })
                           : tWork("radar_scanning", { found: foundAgents.length, total: localDiscoveryItems.length })}
                      </div>
                      <div className="w-full space-y-3 flex-grow">
                        {localDiscoveryItems.filter((item) => foundAgents.includes(item.id)).map((item) => (
                          <div key={item.id} className="flex justify-between items-center bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm animate-[fade-in_0.3s_ease-out] shadow-sm gap-4">
                            <div className="flex items-center gap-4 min-w-0">
                              <div className="w-10 h-10 shrink-0 border border-foreground/30 bg-black/50 flex items-center justify-center text-[11px] font-bold tracking-[0.18em]">
                                {discoveryBadge(item)}
                              </div>
                              <div className="min-w-0">
                                <div className="text-sm font-bold truncate">{item.title}</div>
                                <div className="text-[10px] opacity-70 uppercase tracking-widest truncate">{discoverySummary(item)}</div>
                              </div>
                            </div>
                            <div className="flex flex-col items-end gap-1.5 shrink-0">
                              <span className="text-[10px] text-green-500 font-bold bg-green-500/10 px-2 py-0.5 rounded">{tWork("radar_found")}</span>
                              <label className="flex items-center gap-1.5 cursor-pointer group/chk">
                                <span className="text-[9px] sm:text-[10px] opacity-70 group-hover/chk:opacity-100 uppercase tracking-widest">{tWork("radar_join_network")}</span>
                                <div className={`w-3 h-3 sm:w-4 sm:h-4 border-2 ${checkedToJoin.includes(item.id) ? 'bg-foreground border-foreground' : 'border-foreground/50'} flex items-center justify-center transition-colors`}>
                                  {checkedToJoin.includes(item.id) && <span className="text-background text-[10px] leading-none font-bold">✓</span>}
                                </div>
                                <input 
                                  type="checkbox" 
                                  className="hidden"
                                  checked={checkedToJoin.includes(item.id)}
                                  onChange={e => {
                                    if (e.target.checked) setCheckedToJoin(prev => [...prev, item.id]);
                                    else setCheckedToJoin(prev => prev.filter(n => n !== item.id));
                                  }}
                                />
                              </label>
                            </div>
                          </div>
                        ))}
                        {scanComplete && localDiscoveryItems.length === 0 && (
                          <div className="border border-foreground/20 bg-foreground/5 p-4 text-xs opacity-80 uppercase tracking-widest text-center">
                            {tWork("local_node_discovery_empty")}
                          </div>
                        )}
                      </div>

                      <div className="flex justify-end gap-4 mt-6 w-full shrink-0 border-t border-foreground/10 pt-4">
                         {scanComplete && (
                           <button 
                             className="hover:underline opacity-80 hover:opacity-100 text-xs mr-auto transition-opacity"
                             onClick={() => {
                               void handleDiscoverAgents();
                             }}
                           >
                             {tWork("btn_rescan")}
                           </button>
                         )}
                         <button 
                           className="hover:underline opacity-70 hover:opacity-100 text-xs"
                           onClick={() => {
                              setIsDiscovering(false);
                              setTimeout(() => inputRef.current?.focus(), 50);
                           }}
                         >
                           {tWork("btn_cancel")}
                         </button>
                         <button 
                           className="bg-foreground text-background font-bold px-4 py-1 hover:opacity-80 transition-opacity text-xs disabled:opacity-50"
                           onClick={() => {
                              void handleRegisterSelectedAgents();
                           }}
                           disabled={localActionBusyKey === "register-selected"}
                         >
                           {tWork("btn_confirm_join")}
                         </button>
                      </div>
                    </div>
                  ) : localAttachReady || localDiscoveryItems.length > 0 || localManagedRegistrations.length > 0 || localAcpSessions.length > 0 ? (
                    <div className="space-y-4">
                      <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                        <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-80">
                          <span>{tWork("local_discovered_agents_label")}</span>
                          <span>{tWork("local_node_discovery_summary", { count: localDiscoveryItems.length })}</span>
                        </div>
                        <div className="space-y-3">
                          {localDiscoveryItems.length > 0 ? localDiscoveryItems.map((item) => {
                            const registration = managedRegistrationForDiscovery(item.id, localManagedRegistrations);

                            return (
                              <div key={item.id} className="flex justify-between items-center bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm gap-4">
                                <div className="flex items-center gap-4 min-w-0">
                                  <div className="w-10 h-10 shrink-0 border border-foreground/30 bg-black/60 flex items-center justify-center text-[11px] font-bold tracking-[0.18em]">
                                    {discoveryBadge(item)}
                                  </div>
                                  <div className="min-w-0">
                                    <div className="text-sm font-bold truncate">{item.title}</div>
                                    <div className="text-[10px] opacity-70 uppercase tracking-widest truncate">{discoverySummary(item)}</div>
                                  </div>
                                </div>
                                <div className="flex flex-col items-end gap-2 shrink-0">
                                  <div className="text-[10px] uppercase tracking-widest opacity-70 text-right max-w-[140px]">
                                    {registration ? tWork("local_registered_badge") : item.agentcoin_compatibility?.attachable_today ? tWork("local_node_attachable") : tWork("local_node_inspect")}
                                  </div>
                                  <button
                                    className="bg-foreground text-background font-bold px-3 py-1 hover:opacity-80 transition-opacity text-[10px] uppercase tracking-widest disabled:opacity-50"
                                    onClick={() => {
                                      void handleRegisterDiscoveredAgent(item);
                                    }}
                                    disabled={Boolean(registration) || localActionBusyKey === `register:${item.id}` || !localNodeToken.trim()}
                                  >
                                    {registration ? tWork("local_registered_badge") : tWork("local_register")}
                                  </button>
                                </div>
                              </div>
                            );
                          }) : (
                            <div className="border border-foreground/20 bg-foreground/5 p-4 text-xs opacity-80 uppercase tracking-widest text-center">
                              {tWork("local_node_discovery_empty")}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                        <div className="flex flex-col gap-2 text-[10px] uppercase tracking-[0.18em] opacity-80 sm:flex-row sm:items-center sm:justify-between">
                          <span>{tWork("local_multimodal_label")}</span>
                          <span className="normal-case tracking-normal text-[10px] opacity-60">{tWork("local_multimodal_hint")}</span>
                        </div>

                        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
                          <div className="border border-foreground/10 bg-black/20 p-3 space-y-3">
                            <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                              <span>{tWork("local_multimodal_kind")}</span>
                              <input
                                type="text"
                                className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                                value={localMultimodalKind}
                                onChange={(e) => setLocalMultimodalKind(e.target.value)}
                                placeholder={tWork("local_multimodal_kind_placeholder")}
                              />
                            </label>

                            <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                              <span>{tWork("local_multimodal_prompt")}</span>
                              <textarea
                                className="min-h-28 resize-y bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                                value={localMultimodalPrompt}
                                onChange={(e) => setLocalMultimodalPrompt(e.target.value)}
                                placeholder={tWork("local_multimodal_prompt_placeholder")}
                              />
                            </label>

                            <div className="space-y-2 text-[10px] uppercase tracking-[0.14em] opacity-80">
                              <div>{tWork("local_multimodal_files")}</div>
                              <div className="normal-case tracking-normal opacity-60">{tWork("local_multimodal_files_hint")}</div>
                              <div className="normal-case tracking-normal opacity-60">
                                {tWork("local_multimodal_attachment_limit", {
                                  count: MAX_MULTIMODAL_FILES,
                                  sizeMb: String(MAX_MULTIMODAL_FILE_BYTES / (1024 * 1024)),
                                })}
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <label className="cursor-pointer border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10">
                                  {tWork("local_multimodal_add_files")}
                                  <input type="file" multiple className="hidden" onChange={(e) => { void handleMultimodalFilesSelected(e); }} />
                                </label>
                                <button
                                  className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                                  onClick={() => setLocalMultimodalAttachments([])}
                                  disabled={localMultimodalAttachments.length === 0}
                                >
                                  {tWork("local_multimodal_clear_files")}
                                </button>
                                <button
                                  className="bg-foreground text-background px-3 py-2 text-[10px] uppercase tracking-widest hover:opacity-80 disabled:opacity-50"
                                  onClick={() => {
                                    void handleDispatchMultimodalTask();
                                  }}
                                  disabled={localActionBusyKey === "dispatch-task"}
                                >
                                  {tWork("local_multimodal_dispatch")}
                                </button>
                              </div>
                            </div>

                            {localMultimodalError && (
                              <div className="text-[10px] normal-case tracking-normal text-red-400">{localMultimodalError}</div>
                            )}
                            {localMultimodalNotice && (
                              <div className="text-[10px] normal-case tracking-normal text-green-400">{localMultimodalNotice}</div>
                            )}
                          </div>

                          <div className="border border-foreground/10 bg-black/20 p-3 space-y-3">
                            <TaskMediaGallery
                              title={tWork("local_multimodal_input_assets")}
                              assets={localMultimodalAttachments.map((item) => ({
                                id: item.id,
                                label: item.name,
                                mimeType: item.mime_type,
                                kind: item.kind,
                                source: "draft",
                                size: item.size,
                                dataUrl: item.data_url,
                                text: item.text_preview,
                              }))}
                              emptyLabel={tWork("local_multimodal_no_input_assets")}
                              downloadLabel={tWork("local_multimodal_download")}
                            />

                            {localMultimodalAttachments.length > 0 && (
                              <div className="flex flex-wrap gap-2">
                                {localMultimodalAttachments.map((item) => (
                                  <button
                                    key={item.id}
                                    className="border border-foreground/20 px-2 py-1 text-[10px] normal-case tracking-normal hover:bg-foreground/10"
                                    onClick={() => {
                                      setLocalMultimodalAttachments((prev) => prev.filter((entry) => entry.id !== item.id));
                                    }}
                                  >
                                    {tWork("local_multimodal_remove_file")}: {item.name}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                        <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-80">
                          <span>{tWork("local_managed_label")}</span>
                          <button
                            onClick={() => {
                              void refreshLocalRuntimeState();
                            }}
                            className="hover:underline disabled:opacity-50"
                            disabled={localRuntimeBusy}
                          >
                            {tWork("local_runtime_refresh")}
                          </button>
                        </div>
                        <div className="text-[10px] uppercase tracking-[0.14em] opacity-70">
                          {tWork("local_managed_summary", { registrations: localManagedRegistrations.length, running: runningRegistrations })}
                        </div>
                        <div className="space-y-3">
                          {localManagedRegistrations.length > 0 ? localManagedRegistrations.map((registration) => {
                            const session = acpSessionForRegistration(registration.registration_id, localAcpSessions);
                            const supportsAcp = (registration.protocols || []).includes("acp");

                            return (
                              <div key={registration.registration_id} className="flex justify-between items-start gap-4 bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm">
                                <div className="min-w-0 space-y-1">
                                  <div className="text-sm font-bold truncate">{registration.title || registration.registration_id}</div>
                                  <div className="text-[10px] opacity-70 uppercase tracking-widest truncate">{registration.registration_id}</div>
                                  <div className="text-[10px] opacity-65 truncate">
                                    {(registration.protocols || []).join(" / ") || tWork("remote_peers_no_protocols")}
                                  </div>
                                  <div className="text-[10px] opacity-65 truncate">
                                    {tWork("local_runtime_status_label")}: {(registration.status || "unknown").toUpperCase()}
                                    {registration.pid ? ` / PID ${registration.pid}` : ""}
                                    {registration.transport ? ` / ${registration.transport}` : ""}
                                  </div>
                                  {registration.last_error && <div className="text-[10px] text-red-400 truncate">{registration.last_error}</div>}
                                </div>
                                <div className="shrink-0 flex flex-col items-end gap-2">
                                  {registration.status === "running" ? (
                                    <button
                                      className="hover:underline text-[10px] uppercase tracking-widest disabled:opacity-50"
                                      onClick={() => {
                                        void handleStopRegistration(registration);
                                      }}
                                      disabled={localActionBusyKey === `stop:${registration.registration_id}`}
                                    >
                                      {tWork("local_stop")}
                                    </button>
                                  ) : (
                                    <button
                                      className="hover:underline text-[10px] uppercase tracking-widest disabled:opacity-50"
                                      onClick={() => {
                                        void handleStartRegistration(registration);
                                      }}
                                      disabled={localActionBusyKey === `start:${registration.registration_id}`}
                                    >
                                      {tWork("local_start")}
                                    </button>
                                  )}
                                  {supportsAcp && (
                                    <button
                                      className="bg-foreground text-background font-bold px-3 py-1 hover:opacity-80 transition-opacity text-[10px] uppercase tracking-widest disabled:opacity-50"
                                      onClick={() => {
                                        void handleOpenAcpSession(registration);
                                      }}
                                      disabled={Boolean(session) || localActionBusyKey === `open-acp:${registration.registration_id}`}
                                    >
                                      {session ? tWork("local_acp_opened") : tWork("local_open_acp")}
                                    </button>
                                  )}
                                </div>
                              </div>
                            );
                          }) : (
                            <div className="border border-foreground/20 bg-foreground/5 p-4 text-xs opacity-80 uppercase tracking-widest text-center">
                              {tWork("local_managed_empty")}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                        <div className="flex flex-col gap-2 text-[10px] uppercase tracking-[0.18em] opacity-80 sm:flex-row sm:items-center sm:justify-between">
                          <span>{tWork("local_acp_label")}</span>
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
                            <span>{tWork("local_acp_summary", { sessions: localAcpSessions.length, ready: transportReadySessions, frames: totalCapturedFrames })}</span>
                            <button
                              onClick={() => {
                                void refreshLocalRuntimeState();
                              }}
                              className="text-left hover:underline disabled:opacity-50 sm:text-right"
                              disabled={localRuntimeBusy}
                            >
                              {tWork("local_runtime_refresh")}
                            </button>
                          </div>
                        </div>
                        <div className="border border-foreground/10 bg-black/20 p-3 text-[10px] uppercase tracking-[0.14em] opacity-75 space-y-1">
                          <div>{tWork("local_acp_boundary_title")}</div>
                          {localAcpBoundary?.transport_ready && <div>{tWork("local_acp_boundary_transport_ready")}</div>}
                          {localAcpBoundary?.protocol_messages_implemented === false && <div>{tWork("local_acp_boundary_protocol_pending")}</div>}
                          {localAcpBoundary?.server_response_parsing_implemented !== true && <div>{tWork("local_acp_boundary_capture_hint")}</div>}
                        </div>
                        <div className="space-y-3">
                          {localAcpSessions.length > 0 ? localAcpSessions.map((session) => {
                            const registration = localManagedRegistrations.find((item) => item.registration_id === session.registration_id);
                            const currentInputs = localSessionTaskInputs[session.session_id] || {
                              taskId: session.last_task_request_intent?.mapping?.agentcoin_task_id || "",
                              serverSessionId: inferAcpServerSessionId(session),
                            };
                            const inferredServerSessionId = inferAcpServerSessionId(session);
                            const selectedTask = taskForId(currentInputs.taskId, localTasks);
                            const latestResponseText = acpFrameText(session.latest_task_response_frame || session.latest_server_frame);
                            const taskResultText = taskResultPreview(selectedTask);
                            const responsePreview = latestResponseText ? truncatePreview(latestResponseText, 1200) : "";
                            const inputAssets = taskInputAssets(selectedTask);
                            const outputAssets = taskOutputAssets(selectedTask);

                            return (
                              <div key={session.session_id} className="flex flex-col gap-4 bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm xl:flex-row xl:items-start">
                                <div className="min-w-0 flex-1 space-y-3">
                                  <div className="flex flex-col gap-2 border-b border-foreground/10 pb-3 sm:flex-row sm:items-start sm:justify-between">
                                    <div className="min-w-0 space-y-1">
                                      <div className="text-sm font-bold truncate">{registration?.title || session.registration_id}</div>
                                      <div className="text-[10px] opacity-70 uppercase tracking-widest break-all">{session.session_id}</div>
                                    </div>
                                    <div className="flex flex-wrap gap-2 text-[10px] uppercase tracking-[0.14em] opacity-70">
                                      <span className="border border-foreground/15 bg-black/20 px-2 py-1">{(session.status || "unknown").toUpperCase()}</span>
                                      {session.transport && <span className="border border-foreground/15 bg-black/20 px-2 py-1">{session.transport}</span>}
                                      {session.protocol && <span className="border border-foreground/15 bg-black/20 px-2 py-1">{session.protocol}</span>}
                                    </div>
                                  </div>

                                  <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                                    <div className="border border-foreground/10 bg-black/20 p-2 text-[10px] uppercase tracking-[0.14em]">
                                      <div className="opacity-55">{tWork("local_acp_handshake_label")}</div>
                                      <div className="mt-1 normal-case tracking-normal opacity-90 break-words">{session.handshake_state || "-"}</div>
                                    </div>
                                    <div className="border border-foreground/10 bg-black/20 p-2 text-[10px] uppercase tracking-[0.14em]">
                                      <div className="opacity-55">{tWork("local_acp_protocol_label")}</div>
                                      <div className="mt-1 normal-case tracking-normal opacity-90 break-words">{session.protocol_state || "-"}</div>
                                    </div>
                                    <div className="border border-foreground/10 bg-black/20 p-2 text-[10px] uppercase tracking-[0.14em]">
                                      <div className="opacity-55">{tWork("local_acp_frames_label")}</div>
                                      <div className="mt-1 normal-case tracking-normal opacity-90">{session.server_frames_seen || 0}</div>
                                    </div>
                                    <div className="border border-foreground/10 bg-black/20 p-2 text-[10px] uppercase tracking-[0.14em]">
                                      <div className="opacity-55">{tWork("local_acp_turns_label")}</div>
                                      <div className="mt-1 normal-case tracking-normal opacity-90">{session.summary?.turn_count || 0}</div>
                                    </div>
                                  </div>

                                  <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                                    <div className="border border-foreground/10 bg-black/20 p-3 space-y-3">
                                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-70">{tWork("local_acp_task_panel_title")}</div>
                                      <div className="grid grid-cols-1 gap-2">
                                        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                                          <span>{tWork("local_acp_task_select")}</span>
                                          <select
                                            className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                                            value={currentInputs.taskId}
                                            onChange={(e) => {
                                              const value = e.target.value;
                                              setLocalSessionTaskInputs((prev) => ({
                                                ...prev,
                                                [session.session_id]: {
                                                  taskId: value,
                                                  serverSessionId: prev[session.session_id]?.serverSessionId || currentInputs.serverSessionId,
                                                },
                                              }));
                                            }}
                                          >
                                            <option value="">{tWork("local_acp_task_select_placeholder")}</option>
                                            {localTasks.map((task) => (
                                              <option key={task.id} value={task.id}>
                                                {taskOptionLabel(task)}
                                              </option>
                                            ))}
                                          </select>
                                        </label>
                                        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                                          <span>{tWork("local_acp_server_session")}</span>
                                          <input
                                            type="text"
                                            className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                                            value={currentInputs.serverSessionId}
                                            onChange={(e) => {
                                              const value = e.target.value;
                                              setLocalSessionTaskInputs((prev) => ({
                                                ...prev,
                                                [session.session_id]: {
                                                  taskId: prev[session.session_id]?.taskId || currentInputs.taskId,
                                                  serverSessionId: value,
                                                },
                                              }));
                                            }}
                                            placeholder={tWork("local_acp_server_session_placeholder")}
                                          />
                                        </label>
                                      </div>

                                      {inferredServerSessionId && (
                                        <div className="text-[10px] opacity-65 normal-case tracking-normal break-all">
                                          {tWork("local_acp_server_session_inferred")}: {inferredServerSessionId}
                                        </div>
                                      )}

                                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-[10px] normal-case tracking-normal opacity-75">
                                        <div>
                                          <span className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_updated_label")}</span>
                                          <div className="mt-1 break-words">{acpSessionUpdatedAt(session)}</div>
                                        </div>
                                        <div>
                                          <span className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_pending_requests_label")}</span>
                                          <div className="mt-1 break-words">{acpPendingRequestSummary(session)}</div>
                                        </div>
                                      </div>

                                      {selectedTask ? (
                                        <div className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal opacity-85 space-y-2 break-words">
                                          <div>
                                            <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_task_summary_label")}</div>
                                            <div className="mt-1">{taskSummary(selectedTask)}</div>
                                          </div>
                                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                                            <div>
                                              <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_task_status_label")}</div>
                                              <div className="mt-1">
                                                {(selectedTask.status || "unknown").toUpperCase()}
                                                {selectedTask.completed_at ? ` / ${selectedTask.completed_at}` : ""}
                                              </div>
                                            </div>
                                            <div>
                                              <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_task_meta_label")}</div>
                                              <div className="mt-1">{taskMetaSummary(selectedTask)}</div>
                                            </div>
                                          </div>
                                          <div>
                                            <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_task_result_label")}</div>
                                            <div className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-words pr-1">
                                              {taskResultText || tWork("local_acp_task_result_pending")}
                                            </div>
                                          </div>
                                          <TaskMediaGallery
                                            title={tWork("local_multimodal_input_assets")}
                                            assets={inputAssets}
                                            emptyLabel={tWork("local_multimodal_no_input_assets")}
                                            downloadLabel={tWork("local_multimodal_download")}
                                          />
                                          <TaskMediaGallery
                                            title={tWork("local_multimodal_output_assets")}
                                            assets={outputAssets}
                                            emptyLabel={tWork("local_multimodal_no_output_assets")}
                                            downloadLabel={tWork("local_multimodal_download")}
                                          />
                                        </div>
                                      ) : (
                                        <div className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal opacity-75">
                                          {tWork("local_acp_task_empty")}
                                        </div>
                                      )}
                                    </div>

                                    <div className="border border-foreground/10 bg-black/20 p-3 space-y-2">
                                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-70">{tWork("local_acp_response_label")}</div>
                                      {responsePreview ? (
                                        <div className="max-h-56 overflow-y-auto whitespace-pre-wrap break-words pr-1 text-[10px] normal-case tracking-normal opacity-85">
                                          {responsePreview}
                                        </div>
                                      ) : (
                                        <div className="text-[10px] normal-case tracking-normal opacity-65">
                                          {tWork("local_acp_response_empty")}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>

                                <div className="w-full shrink-0 xl:w-[220px]">
                                  <div className="border border-foreground/10 bg-black/20 p-3 space-y-2">
                                    <div className="text-[10px] uppercase tracking-[0.14em] opacity-65 normal-case">
                                      {tWork("local_acp_controls_hint")}
                                    </div>
                                  <button
                                    className="w-full border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                    onClick={() => {
                                      void handleInitializeAcpSession(session);
                                    }}
                                    disabled={localActionBusyKey === `initialize-acp:${session.session_id}` || session.status !== "open"}
                                  >
                                    {tWork("local_acp_initialize")}
                                  </button>
                                  <button
                                    className="w-full border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                    onClick={() => {
                                      void handlePollAcpSession(session);
                                    }}
                                    disabled={localActionBusyKey === `poll-acp:${session.session_id}` || session.status !== "open"}
                                  >
                                    {tWork("local_acp_poll")}
                                  </button>
                                  <button
                                    className="w-full border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                    onClick={() => {
                                      void handleSendAcpTaskRequest(session);
                                    }}
                                    disabled={localActionBusyKey === `task-request:${session.session_id}` || session.status !== "open"}
                                  >
                                    {tWork("local_acp_task_request")}
                                  </button>
                                  <button
                                    className="w-full bg-foreground text-background px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:opacity-80 disabled:opacity-50"
                                    onClick={() => {
                                      void handleApplyAcpTaskResult(session);
                                    }}
                                    disabled={localActionBusyKey === `apply-result:${session.session_id}` || session.status !== "open"}
                                  >
                                    {tWork("local_acp_apply_result")}
                                  </button>
                                  <button
                                    className="w-full border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                    onClick={() => {
                                      void handleCloseAcpSession(session);
                                    }}
                                    disabled={localActionBusyKey === `close-acp:${session.session_id}`}
                                  >
                                    {tWork("local_acp_close")}
                                  </button>
                                  </div>
                                </div>
                              </div>
                            );
                          }) : (
                            <div className="border border-foreground/20 bg-foreground/5 p-4 text-xs opacity-80 uppercase tracking-widest text-center">
                              {tWork("local_acp_empty")}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-5">
                      {agents.map((agent, idx) => (
                      <div key={idx} className="flex flex-col text-foreground animate-fade-in group">
                        <div className="flex justify-between items-center bg-foreground/5 p-4 px-5 border-2 border-foreground/10 hover:border-foreground/30 hover:bg-foreground/10 transition-all shadow-sm rounded-sm">
                          <div className="flex items-center gap-6">
                            <pre className={`font-bold text-[10px] sm:text-xs opacity-80 group-hover:opacity-100 ${agent.accent} transition-all drop-shadow-sm leading-none m-0 select-none tracking-tighter`}>
                              {agent.icon}
                            </pre>
                            <div className="flex flex-col justify-center gap-1.5">
                              <span className="text-base font-bold truncate max-w-[140px] sm:max-w-none">{agent.name}</span>
                              <span className="text-[10px] opacity-60 uppercase tracking-widest bg-foreground/10 px-2 py-0.5 rounded-sm w-fit border border-foreground/20">{tWork("ai_subsystem")}</span>
                            </div>
                          </div>
                          <div className="flex flex-col items-end gap-2 text-xs opacity-80 pl-4 h-full justify-center min-h-[40px]">
                             {agent.status === 'online' ? (
                                <div className="flex items-center gap-2 mt-2">
                                  <div className="transform scale-[0.4] origin-right mr-[-12px] sm:mr-[-16px]"><AnatomicalHeart isOnline={true} /></div>
                                  <span className="text-green-500 font-bold w-[45px] text-right text-sm">{agent.latency}ms</span>
                                </div>
                             ) : (
                                <div className="flex items-center gap-2 mt-2">
                                  <div className="transform scale-[0.4] origin-right mr-[-12px] sm:mr-[-16px]"><AnatomicalHeart isOnline={false} /></div>
                                  <span className="text-red-500/50 font-bold w-[45px] text-right text-sm">ERR</span>
                                </div>
                             )}
                          </div>
                        </div>
                      </div>
                    ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
            
            <div className="mt-8 text-xs text-muted-foreground border-t border-foreground/30 pt-4 shrink-0">
              <p>{tWork("clear_hint_prefix")}<span className="text-foreground font-bold">clear</span>{tWork("clear_hint_suffix")}</p>
            </div>
          </div>
        </div>

      </main>

      {/* Workflow Publish Dialog/Modal */}
      {showWorkflowModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="bg-background border-2 border-foreground p-6 max-w-xl w-full flex flex-col gap-6 shadow-[0_0_40px_rgba(var(--foreground-rgb),0.15)] animate-[fade-in_0.2s_ease-out]">
            <div className="flex justify-between items-center border-b-2 border-foreground pb-4">
              <h2 className="text-lg font-bold uppercase tracking-widest">{tWork("workflow_publish_title", { defaultValue: "[ WORKFLOW // ORCHESTRATION ]" })}</h2>
              <button onClick={() => setShowWorkflowModal(false)} className="hover:bg-foreground hover:text-background px-2 py-1 font-bold transition-colors">
                ✕
              </button>
            </div>
            
            <div className="space-y-5">
               <div>
                  <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80 mb-2">
                     <span className="w-1.5 h-1.5 bg-foreground"></span>
                     {tWork("workflow_target", { defaultValue: "Target Subsystem" })}
                  </label>
                  <select 
                    className="w-full bg-foreground/5 border border-foreground/30 p-2.5 outline-none focus:border-foreground normal-case tracking-normal text-sm"
                    value={localMultimodalKind}
                    onChange={(e) => setLocalMultimodalKind(e.target.value)}
                  >
                     <option value="generic">{tWork("workflow_target_generic", { defaultValue: "Generic Match (Auto)" })}</option>
                     {localDiscoveryItems.map(i => <option key={i.id} value={i.type || i.id}>[{i.id.slice(0,6)}] {i.title}</option>)}
                     <option value="copilot">{tWork("workflow_target_copilot", { defaultValue: "Copilot Override" })}</option>
                  </select>
               </div>
               
               <div>
                  <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80 mb-2">
                     <span className="w-1.5 h-1.5 bg-foreground"></span>
                     {tWork("workflow_prompt", { defaultValue: "Execution Prompt" })}
                  </label>
                  <textarea 
                    className="w-full min-h-32 bg-foreground/5 border border-foreground/30 p-3 outline-none focus:border-foreground text-sm normal-case tracking-normal custom-scrollbar"
                    placeholder={tWork("workflow_prompt_placeholder", { defaultValue: "Enter your multi-modal task instructions here..." })}
                    value={localMultimodalPrompt}
                    onChange={(e) => setLocalMultimodalPrompt(e.target.value)}
                  />
               </div>
               
               <div className="grid grid-cols-2 gap-4">
                  <div className="border border-foreground/20 p-3 space-y-2">
                     <div className="text-[10px] uppercase tracking-widest opacity-60 m-0">Files Loaded: {localMultimodalAttachments.length}</div>
                     <div className="text-[10px] uppercase tracking-widest opacity-60">Limit: {MAX_MULTIMODAL_FILES} ({String(MAX_MULTIMODAL_FILE_BYTES / (1024 * 1024))}MB)</div>
                  </div>
                  <div className="flex flex-col justify-end gap-2">
                     <label className="cursor-pointer border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 text-center transition-colors">
                       {tWork("local_multimodal_add_files", { defaultValue: "+ ADD FILES" })}
                       <input type="file" multiple className="hidden" onChange={(e) => { void handleMultimodalFilesSelected(e); }} />
                     </label>
                     <button
                       className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50 transition-colors"
                       onClick={() => setLocalMultimodalAttachments([])}
                       disabled={localMultimodalAttachments.length === 0}
                     >
                       {tWork("local_multimodal_clear_files", { defaultValue: "CLEAR ASSETS" })}
                     </button>
                  </div>
               </div>

               {localMultimodalError && (
                 <div className="text-xs normal-case tracking-normal text-red-500 font-bold border border-red-500/20 bg-red-500/10 p-2">
                   ERR: {localMultimodalError}
                 </div>
               )}
               
               <div className="pt-4 border-t border-foreground/20">
                 <button 
                   className="w-full bg-foreground text-background font-bold text-sm py-3.5 uppercase tracking-widest hover:opacity-85 hover:scale-[0.99] transition-all disabled:opacity-50 disabled:scale-100"
                   onClick={() => {
                      void handleDispatchMultimodalTask();
                      if (!localMultimodalError) {
                         setTimeout(() => setShowWorkflowModal(false), 500);
                      }
                   }}
                   disabled={!localMultimodalPrompt.trim() && localMultimodalAttachments.length === 0}
                 >
                   {tWork("workflow_submit", { defaultValue: "EXECUTE_WORKFLOW" })}
                 </button>
               </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
