"use client";

import { useState, useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useTheme } from "next-themes";
import { useRouter, usePathname } from "next/navigation";
import WalletWindow from "./WalletWindow";

type WorkspaceMessageTranslator = (
  key: string,
  values?: Record<string, string | number>,
) => string;

type WorkflowExecuteOutcome =
  | { status: "accepted"; payload: any }
  | { status: "payment-required"; payload: { payment: any; quoteDetails: string } };

type WorkflowPaymentState = {
  payment: any;
  quoteDetails: string;
  payer: string;
  txHash: string;
  receipt: any | null;
  receiptAttestation: any | null;
  renterToken: any | null;
};

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

type LocalAcpListedSession = {
  sessionId: string;
  cwd?: string;
  title?: string;
  updatedAt?: string;
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
  latest_loaded_session_update?: LocalAcpFrame;
  task_response_frame?: LocalAcpFrame;
  latest_task_response_frame?: LocalAcpFrame;
  last_task_request_intent?: LocalAcpIntent;
  listed_server_sessions?: LocalAcpListedSession[];
  loaded_server_session_id?: string;
  loaded_session_update_count?: number;
  session_list_response_frame?: LocalAcpFrame;
  session_load_response_frame?: LocalAcpFrame;
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

type TerminalHistoryEntry = {
  type: "user" | "system";
  content: string;
  agentGlyph?: string;
  agentName?: string;
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

type WorkspaceWindowId = "compose" | "node" | "swarm" | "wallet" | "community";

type AlertSummaryGroupId = "total" | "critical" | "watch";

type LocalRuntimeSnapshot = {
  managedRegistrations: LocalManagedRegistration[];
  acpSessions: LocalAcpSession[];
  acpBoundary: LocalAcpBoundary | null;
  tasks: LocalTaskItem[];
};

type TutorialStepId = "rail" | "status" | "alerts" | "workspace";

const INTRO_STORAGE_KEY = "agentcoin-workspace-intro-seen-v1";
const SIDEBAR_WIDTH_STORAGE_KEY = "agentcoin-workspace-sidebar-width-v1";
const SIDEBAR_COLLAPSED_STORAGE_KEY = "agentcoin-workspace-sidebar-collapsed-v1";
const SIDEBAR_WIDTH_DEFAULT = 256;
const SIDEBAR_WIDTH_MIN = 188;
const SIDEBAR_WIDTH_MAX = 520;
const SIDEBAR_WIDTH_COLLAPSED = 112;
const DEFAULT_LOCAL_TASK_KIND = "generic";
const WORKFLOW_TARGET_CUSTOM_VALUE = "__custom__";
const DESKTOP_SIDEBAR_BREAKPOINT = 1024;
const ACP_AUTO_POLL_INTERVAL_MS = 900;
const ACP_AUTO_SETUP_POLL_ATTEMPTS = 8;
const ACP_AUTO_RESPONSE_POLL_ATTEMPTS = 18;
const USE_LEGACY_LANDING_ROUTE = true;

type CriticalActionGuard =
  | {
      type: "stop-registration";
      windowId: "node";
      registrationId: string;
      registrationLabel: string;
    }
  | {
      type: "close-acp-session";
      windowId: "node";
      sessionId: string;
      registrationId: string;
      registrationLabel: string;
    }
  | {
      type: "clear-compose-attachments";
      windowId: "compose";
      attachmentCount: number;
    }
  | {
      type: "disconnect-local-node";
      windowId: "node";
      registrationCount: number;
      sessionCount: number;
      catalogCount: number;
    };

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function lerp(start: number, end: number, t: number): number {
  return start + (end - start) * t;
}

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

function _getBackdropBeamCount(width: number, height: number): number {
  const viewportArea = width * height;
  const baseline = Math.floor(width / 15);
  const areaPenalty = viewportArea > 1_900_000 ? 12 : viewportArea > 1_300_000 ? 6 : 0;
  return Math.max(72, Math.min(128, baseline - areaPenalty));
}

function _getBackdropDprCap(width: number, height: number): number {
  const viewportArea = width * height;
  if (viewportArea > 1_900_000) return 1.3;
  if (viewportArea > 1_300_000) return 1.45;
  return 1.6;
}

let _dustMotes: DustMote[] | null = null;
function _getDust(): DustMote[] {
  if (_dustMotes) return _dustMotes;
  _dustMotes = Array.from({ length: 32 }, (_, i) => {
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

// Cached backdrop resources (recreated only when size changes)
type BackdropGradientBundle = {
  w: number;
  h: number;
  atm: CanvasGradient;
  topFade: CanvasGradient;
  botFade: CanvasGradient;
  scanline: CanvasPattern | null;
};

type BackdropStaticLayerCache = {
  w: number;
  h: number;
  canvas: HTMLCanvasElement;
};

type BackdropGeometry = {
  floorLY: number;
  floorRY: number;
  hSlope: number;
  vpX: number;
  vpY: number;
};

let _gradientCache = new WeakMap<CanvasRenderingContext2D, BackdropGradientBundle>();
let _cachedBackdropStaticLayer: BackdropStaticLayerCache | null = null;

function _createBackdropCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.floor(width));
  canvas.height = Math.max(1, Math.floor(height));
  return canvas;
}

function _resetBackdropCaches(): void {
  _gradientCache = new WeakMap<CanvasRenderingContext2D, BackdropGradientBundle>();
  _cachedBackdropStaticLayer = null;
}

function _getGradients(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const cached = _gradientCache.get(ctx);
  if (cached && cached.w === w && cached.h === h) return cached;

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

  let scanline: CanvasPattern | null = null;
  const scanlineCanvas = typeof OffscreenCanvas !== 'undefined'
    ? new OffscreenCanvas(1, 3)
    : _createBackdropCanvas(1, 3);
  const scanlineContext = scanlineCanvas.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
  if (scanlineContext) {
    scanlineContext.fillStyle = 'rgba(0,0,0,0.06)';
    scanlineContext.fillRect(0, 0, 1, 1);
    scanline = ctx.createPattern(scanlineCanvas, 'repeat');
  }

  const next = { w, h, atm, topFade, botFade, scanline };
  _gradientCache.set(ctx, next);
  return next;
}

function _getBackdropGeometry(width: number, height: number): BackdropGeometry {
  const floorLY = height * 0.82;
  const floorRY = height * 0.3;
  const hSlope = (floorRY - floorLY) / width;
  const vpX = width * 0.72;
  const vpY = floorLY + hSlope * vpX - height * 0.04;
  return { floorLY, floorRY, hSlope, vpX, vpY };
}

function _drawBackdropStaticLayer(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
): void {
  const grads = _getGradients(ctx, width, height);
  const { floorLY, floorRY, vpX, vpY } = _getBackdropGeometry(width, height);

  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = grads.atm;
  ctx.fillRect(0, 0, width, height);

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, floorLY);
  ctx.lineTo(width, floorRY);
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.clip();

  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#fff';

  ctx.beginPath();
  ctx.globalAlpha = 0.03;
  ctx.lineWidth = 0.5;
  for (let c = -36; c <= 36; c++) {
    if (c % 4 === 0) continue;
    const r = c / 36;
    const a = 0.03 * (1 - Math.abs(r) * 0.55);
    if (a < 0.005) continue;
    const ex = vpX + r * width * 3.2;
    ctx.moveTo(vpX, vpY);
    ctx.lineTo(ex, height * 1.4);
  }
  ctx.stroke();

  ctx.setLineDash([height * 0.02, height * 0.01, height * 0.008, height * 0.018]);
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  for (let c = -36; c <= 36; c += 4) {
    const r = c / 36;
    const a = 0.14 * (1 - Math.abs(r) * 0.55);
    if (a < 0.005) continue;
    ctx.moveTo(vpX, vpY);
    ctx.lineTo(vpX + r * width * 3.2, height * 1.4);
  }
  ctx.globalAlpha = 0.1;
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.lineWidth = 0.7;
  ctx.globalAlpha = 0.1;
  for (let row = 0; row < 20; row++) {
    const dep = Math.pow((row + 1) / 20, 2.0);
    const yL = vpY + (floorLY + height * 0.25 - vpY) * (1 + dep * 5.5);
    const yR = vpY + (floorRY + height * 0.25 - vpY) * (1 + dep * 5.5);
    ctx.moveTo(0, yL);
    ctx.lineTo(width, yR);
  }
  ctx.stroke();
  ctx.restore();
  ctx.globalAlpha = 1;

  ctx.fillStyle = grads.topFade;
  ctx.fillRect(0, 0, width, height * 0.12);
  ctx.fillStyle = grads.botFade;
  ctx.fillRect(0, height * 0.86, width, height * 0.14);

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

function _getBackdropStaticLayer(width: number, height: number): HTMLCanvasElement | null {
  if (_cachedBackdropStaticLayer && _cachedBackdropStaticLayer.w === width && _cachedBackdropStaticLayer.h === height) {
    return _cachedBackdropStaticLayer.canvas;
  }

  const canvas = _createBackdropCanvas(width, height);
  const ctx = canvas.getContext('2d', { alpha: false });
  if (!ctx) return null;

  _drawBackdropStaticLayer(ctx, width, height);
  _cachedBackdropStaticLayer = { w: width, h: height, canvas };
  return canvas;
}

function createBackdropBeams(width: number, height: number): BackdropBeam[] {
  const n = _getBackdropBeamCount(width, height);
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
  const { floorLY, floorRY, hSlope, vpX, vpY } = _getBackdropGeometry(width, height);
  const staticLayer = _getBackdropStaticLayer(width, height);

  if (staticLayer) {
    ctx.globalAlpha = 1;
    ctx.drawImage(staticLayer, 0, 0, width, height);
  } else {
    _drawBackdropStaticLayer(ctx, width, height);
  }

  // ?? 1. Vertical beam wall (batched draw calls) ????????????????????
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(width, 0);
  ctx.lineTo(width, floorRY + 1); ctx.lineTo(0, floorLY + 1);
  ctx.closePath();
  ctx.clip();
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#fff';
  ctx.lineCap = 'butt';

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
      const gap = Math.max(bw * 4, 6);
      const dotOff = (t * b.speed * 0.6 + b.phase) % gap;
      const r = bw * 0.6;
      const useRect = r < 1.5;
      let y = sBot - dotOff;

      while (y >= sTop - gap) {
        if (y >= sTop && y <= sBot) {
          const edgeDist = Math.min(y - sTop, sBot - y);
          const edgeF = Math.min(1, edgeDist / (segH * 0.15 + 1));
          const a = bi * b.blurA * edgeF;
          if (a > 0.01) {
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

  if (solidBeams.length > 0) {
    ctx.beginPath();
    let hasBase = false;
    for (const s of solidBeams) {
      const a = s.bi * s.blurA * 0.12;
      if (a < 0.005) continue;
      if (!hasBase) { ctx.globalAlpha = 0.04; ctx.lineWidth = 12; hasBase = true; }
      ctx.moveTo(s.bx, s.wallH); ctx.lineTo(s.bx, 0);
    }
    if (hasBase) ctx.stroke();

    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.02;
      ctx.lineWidth = s.bw * 26;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.07;
      ctx.lineWidth = s.bw * 9;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.22;
      ctx.lineWidth = s.bw * 3;
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }

    for (const s of solidBeams) {
      ctx.globalAlpha = s.bi * s.blurA * 0.78;
      ctx.lineWidth = Math.max(0.5, s.bw * 0.65);
      ctx.beginPath(); ctx.moveTo(s.bx, s.sBot); ctx.lineTo(s.bx, s.sTop); ctx.stroke();
    }
  }

  ctx.globalAlpha = 1;
  ctx.restore();

  // ?? 2. Perspective floor dynamics ????????????????????????????????
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, floorLY); ctx.lineTo(width, floorRY);
  ctx.lineTo(width, height); ctx.lineTo(0, height);
  ctx.closePath();
  ctx.clip();

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

  // ?? 3. Dust motes (minimal) ??????????????????????????????????????
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
}

type RichBackdropBeam = {
  x: number;
  depth: number;
  speed: number;
  phase: number;
  width: number;
  intensity: number;
  length: number;
  isDotted: boolean;
  twinkle: number;
};

type RichBackdropLane = {
  anchorX: number;
  speed: number;
  phase: number;
  width: number;
  intensity: number;
  length: number;
  isDotted: boolean;
};

type RichBackdropDust = {
  x: number;
  y: number;
  depth: number;
  size: number;
  alpha: number;
  driftX: number;
  driftY: number;
  phase: number;
  speed: number;
};

type RichBackdropProjection = {
  horizonLeftY: number;
  horizonRightY: number;
  vanishX: number;
  vanishY: number;
  getHorizonY: (x: number) => number;
};

type RichBackdropSprites = {
  soft: HTMLCanvasElement;
  core: HTMLCanvasElement;
  haze: HTMLCanvasElement;
};

type RichBackdropScene = {
  projection: RichBackdropProjection;
  beams: RichBackdropBeam[];
  lanes: RichBackdropLane[];
  dust: RichBackdropDust[];
  staticLayer: HTMLCanvasElement;
  sprites: RichBackdropSprites;
};

let richBackdropSpritesCache: RichBackdropSprites | null = null;

function seededUnit(index: number, factor: number, offset = 0): number {
  const seed = Math.sin((index + 1) * factor + offset) * 43758.5453123;
  return seed - Math.floor(seed);
}

function createRichBackdropCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.floor(width));
  canvas.height = Math.max(1, Math.floor(height));
  return canvas;
}

function createRichGlowSprite(size: number, brightStop: number, falloffStop: number): HTMLCanvasElement {
  const canvas = createRichBackdropCanvas(size, size);
  const context = canvas.getContext('2d');
  if (!context) return canvas;

  const radius = size / 2;
  const gradient = context.createRadialGradient(radius, radius, radius * 0.05, radius, radius, radius);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(brightStop, 'rgba(255,255,255,0.88)');
  gradient.addColorStop(falloffStop, 'rgba(255,255,255,0.18)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  return canvas;
}

function getRichBackdropSprites(): RichBackdropSprites {
  if (richBackdropSpritesCache) return richBackdropSpritesCache;

  richBackdropSpritesCache = {
    soft: createRichGlowSprite(120, 0.12, 0.48),
    core: createRichGlowSprite(72, 0.2, 0.34),
    haze: createRichGlowSprite(192, 0.08, 0.72),
  };

  return richBackdropSpritesCache;
}

function getRichBackdropProjection(width: number, height: number): RichBackdropProjection {
  const horizonLeftY = height * 0.84;
  const horizonRightY = height * 0.33;
  const horizonSlope = (horizonRightY - horizonLeftY) / width;
  const vanishX = width * 0.72;
  const vanishY = Math.max(height * 0.18, horizonLeftY + horizonSlope * vanishX - height * 0.12);

  return {
    horizonLeftY,
    horizonRightY,
    vanishX,
    vanishY,
    getHorizonY: (x: number) => horizonLeftY + horizonSlope * x,
  };
}

function getRichBackdropFocus(depth: number): number {
  return clamp(1 - Math.abs(depth - 0.42) / 0.28, 0, 1);
}

function drawRichGlowSprite(
  ctx: CanvasRenderingContext2D,
  sprite: HTMLCanvasElement,
  x: number,
  y: number,
  size: number,
  alpha: number,
): void {
  if (alpha <= 0 || size <= 0.5) return;
  const half = size / 2;
  ctx.globalAlpha = alpha;
  ctx.drawImage(sprite, x - half, y - half, size, size);
}

function createRichBackdropBeams(width: number): RichBackdropBeam[] {
  const beams = Array.from({ length: Math.max(60, Math.floor(width / 18)) }, (_, index) => {
    const spread = seededUnit(index, 127.1);
    const depth = Math.pow(seededUnit(index, 311.7), 0.86);
    const accent = seededUnit(index, 733.1);
    const focus = getRichBackdropFocus(depth);
    const blur = 1 - focus;
    const isDotted = seededUnit(index, 811.3) < (depth > 0.76 ? 0.42 : 0.22);

    let xNorm = 0.06 + spread * 0.88;
    if (depth > 0.78) {
      xNorm = 0.34 + spread * 0.58;
    } else if (depth < 0.16 && accent > 0.74) {
      xNorm = spread < 0.5 ? 0.02 + spread * 0.16 : 0.82 + (spread - 0.5) * 0.32;
    }

    return {
      x: clamp(xNorm, 0.02, 0.98) * width,
      depth,
      speed: 140 + (1 - depth) * 220 + accent * 70,
      phase: spread * 3400 + index * 41,
      width: (isDotted ? 0.7 : 0.55) + focus * (isDotted ? 1.25 : 1.9) + blur * (isDotted ? 1.4 : 4.2),
      intensity: 0.16 + focus * 0.5 + (1 - depth) * 0.22,
      length: 0.08 + focus * 0.18 + blur * 0.06,
      isDotted,
      twinkle: 0.45 + seededUnit(index, 193.1) * 1.6,
    };
  });

  const foregroundColumns: RichBackdropBeam[] = [0.035, 0.082, 0.875, 0.94].map((xNorm, index) => ({
    x: width * xNorm,
    depth: 0.04 + index * 0.025,
    speed: 170 + index * 18,
    phase: index * 800 + 120,
    width: 6 + index * 1.6,
    intensity: 0.14 + index * 0.02,
    length: 0.18,
    isDotted: false,
    twinkle: 0.35 + index * 0.18,
  }));

  return [...beams, ...foregroundColumns].sort((left, right) => right.depth - left.depth);
}

function createRichBackdropLanes(width: number): RichBackdropLane[] {
  return Array.from({ length: Math.max(16, Math.floor(width / 78)) }, (_, index) => {
    const spread = seededUnit(index, 97.13);
    const depth = seededUnit(index, 191.77);

    return {
      anchorX: lerp(-width * 0.18, width * 1.08, Math.pow(spread, 0.92)),
      speed: 0.42 + (1 - depth) * 0.28,
      phase: seededUnit(index, 61.77) + index * 0.137,
      width: 0.9 + (1 - depth) * 2.6,
      intensity: 0.2 + (1 - depth) * 0.58,
      length: 0.08 + (1 - depth) * 0.18,
      isDotted: seededUnit(index, 421.3) < 0.56,
    };
  });
}

function createRichBackdropDust(width: number, height: number, projection: RichBackdropProjection): RichBackdropDust[] {
  return Array.from({ length: 24 }, (_, index) => {
    const spread = seededUnit(index, 53.17);
    const vertical = seededUnit(index, 271.91);
    const depth = seededUnit(index, 613.7);
    const x = width * (0.04 + spread * 0.92);
    const horizonY = projection.getHorizonY(x);
    const y = vertical < 0.72
      ? lerp(height * 0.04, horizonY * 0.96, vertical / 0.72)
      : lerp(horizonY, height * 0.98, (vertical - 0.72) / 0.28);
    const focus = getRichBackdropFocus(depth);
    const blur = 1 - focus;

    return {
      x,
      y,
      depth,
      size: 2 + focus * 3.4 + blur * (depth < 0.18 ? 18 : 8),
      alpha: depth < 0.18 ? 0.11 : 0.025 + focus * 0.055,
      driftX: (seededUnit(index, 887.11) - 0.5) * 8,
      driftY: -4 - seededUnit(index, 991.3) * 12,
      phase: seededUnit(index, 133.31) * Math.PI * 2,
      speed: 0.18 + seededUnit(index, 377.4) * 0.55,
    };
  });
}

function renderRichBackdropStaticLayer(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  projection: RichBackdropProjection,
  beams: RichBackdropBeam[],
  lanes: RichBackdropLane[],
  sprites: RichBackdropSprites,
): void {
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, width, height);

  const mainBloom = ctx.createRadialGradient(width * 0.36, height * 0.48, 0, width * 0.36, height * 0.48, width * 0.82);
  mainBloom.addColorStop(0, 'rgba(255,255,255,0.055)');
  mainBloom.addColorStop(0.32, 'rgba(255,255,255,0.018)');
  mainBloom.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = mainBloom;
  ctx.fillRect(0, 0, width, height);

  const sideBloom = ctx.createRadialGradient(width * 0.84, height * 0.42, 0, width * 0.84, height * 0.42, width * 0.44);
  sideBloom.addColorStop(0, 'rgba(255,255,255,0.03)');
  sideBloom.addColorStop(0.5, 'rgba(255,255,255,0.012)');
  sideBloom.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = sideBloom;
  ctx.fillRect(0, 0, width, height);

  drawRichGlowSprite(ctx, sprites.haze, width * 0.05, height * 0.88, width * 0.24, 0.055);
  drawRichGlowSprite(ctx, sprites.haze, width * 0.93, height * 0.82, width * 0.18, 0.04);

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(width, 0);
  ctx.lineTo(width, projection.horizonRightY + 1);
  ctx.lineTo(0, projection.horizonLeftY + 1);
  ctx.closePath();
  ctx.clip();

  ctx.strokeStyle = '#ffffff';
  ctx.lineCap = 'butt';
  for (const beam of beams) {
    const focus = getRichBackdropFocus(beam.depth);
    const blur = 1 - focus;
    const hitY = projection.getHorizonY(beam.x);

    ctx.globalAlpha = beam.intensity * (0.012 + blur * 0.026 + focus * 0.004);
    ctx.lineWidth = beam.width * (4.8 + blur * 10.5 + focus * 1.6);
    ctx.beginPath();
    ctx.moveTo(beam.x, -height * 0.05);
    ctx.lineTo(beam.x, hitY);
    ctx.stroke();

    if (focus > 0.42 && !beam.isDotted) {
      ctx.globalAlpha = beam.intensity * (0.03 + focus * 0.035);
      ctx.lineWidth = Math.max(0.5, beam.width * 0.8);
      ctx.beginPath();
      ctx.moveTo(beam.x, -height * 0.05);
      ctx.lineTo(beam.x, hitY);
      ctx.stroke();
    }
  }
  ctx.restore();

  ctx.globalAlpha = 0.08;
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 2.4;
  ctx.beginPath();
  ctx.moveTo(0, projection.horizonLeftY);
  ctx.lineTo(width, projection.horizonRightY);
  ctx.stroke();

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, projection.horizonLeftY);
  ctx.lineTo(width, projection.horizonRightY);
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.clip();

  const floorFade = ctx.createLinearGradient(0, projection.horizonRightY, 0, height);
  floorFade.addColorStop(0, 'rgba(0,0,0,0.08)');
  floorFade.addColorStop(0.35, 'rgba(0,0,0,0.42)');
  floorFade.addColorStop(1, 'rgba(0,0,0,0.9)');
  ctx.fillStyle = floorFade;
  ctx.fillRect(0, 0, width, height);

  for (let row = 0; row < 18; row++) {
    const curve = Math.pow((row + 1) / 18, 1.72);
    const yLeft = lerp(projection.horizonLeftY + 1, height * 1.04, curve);
    const yRight = lerp(projection.horizonRightY + 1, height * 1.02, curve);
    ctx.globalAlpha = 0.015 + (1 - curve) * 0.12;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 0.8 + curve * 0.55;
    if (row % 3 === 0) {
      ctx.setLineDash([width * (0.004 + (1 - curve) * 0.004), width * (0.012 + curve * 0.015)]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.beginPath();
    ctx.moveTo(0, yLeft);
    ctx.lineTo(width, yRight);
    ctx.stroke();
  }

  for (const lane of lanes) {
    const startX = lane.anchorX;
    const startY = height * 1.03;
    ctx.globalAlpha = lane.intensity * (lane.isDotted ? 0.018 : 0.042);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = lane.isDotted ? 0.9 : lane.width * 0.42;
    if (lane.isDotted) {
      ctx.setLineDash([height * 0.008, height * 0.016]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.beginPath();
    ctx.moveTo(projection.vanishX, projection.vanishY);
    ctx.lineTo(startX, startY);
    ctx.stroke();
  }

  ctx.setLineDash([]);
  ctx.restore();

  const topFade = ctx.createLinearGradient(0, 0, 0, height * 0.15);
  topFade.addColorStop(0, 'rgba(0,0,0,0.86)');
  topFade.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = topFade;
  ctx.fillRect(0, 0, width, height * 0.15);

  const edgeFade = ctx.createLinearGradient(0, 0, width, 0);
  edgeFade.addColorStop(0, 'rgba(0,0,0,0.36)');
  edgeFade.addColorStop(0.12, 'rgba(0,0,0,0)');
  edgeFade.addColorStop(0.88, 'rgba(0,0,0,0)');
  edgeFade.addColorStop(1, 'rgba(0,0,0,0.22)');
  ctx.fillStyle = edgeFade;
  ctx.fillRect(0, 0, width, height);

  const bottomFade = ctx.createLinearGradient(0, height * 0.76, 0, height);
  bottomFade.addColorStop(0, 'rgba(0,0,0,0)');
  bottomFade.addColorStop(1, 'rgba(0,0,0,0.62)');
  ctx.fillStyle = bottomFade;
  ctx.fillRect(0, height * 0.76, width, height * 0.24);

  ctx.fillStyle = 'rgba(0,0,0,0.09)';
  for (let y = 0; y < height; y += 4) {
    ctx.fillRect(0, y, width, 1);
  }

  ctx.globalAlpha = 1;
}

function buildRichBackdropScene(width: number, height: number): RichBackdropScene {
  const projection = getRichBackdropProjection(width, height);
  const sprites = getRichBackdropSprites();
  const beams = createRichBackdropBeams(width);
  const lanes = createRichBackdropLanes(width);
  const dust = createRichBackdropDust(width, height, projection);
  const staticLayer = createRichBackdropCanvas(width, height);
  const context = staticLayer.getContext('2d');

  if (context) {
    renderRichBackdropStaticLayer(context, width, height, projection, beams, lanes, sprites);
  }

  return {
    projection,
    beams,
    lanes,
    dust,
    staticLayer,
    sprites,
  };
}

function drawRichBackdropWallMotion(
  ctx: CanvasRenderingContext2D,
  width: number,
  projection: RichBackdropProjection,
  beams: RichBackdropBeam[],
  sprites: RichBackdropSprites,
  timeMs: number,
  height: number,
): void {
  const t = timeMs * 0.001;

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(width, 0);
  ctx.lineTo(width, projection.horizonRightY + 1);
  ctx.lineTo(0, projection.horizonLeftY + 1);
  ctx.closePath();
  ctx.clip();

  ctx.strokeStyle = '#ffffff';
  ctx.lineCap = 'round';

  for (const beam of beams) {
    const focus = getRichBackdropFocus(beam.depth);
    const blur = 1 - focus;
    const hitY = projection.getHorizonY(beam.x);
    const shimmer = 0.72 + 0.28 * Math.sin(t * beam.twinkle + beam.phase * 0.0016);
    const beamAlpha = beam.intensity * shimmer;

    if (beam.isDotted) {
      const spacing = Math.max(9, beam.width * (4.8 + blur * 3.8));
      const dotCount = Math.floor(hitY / spacing) + 4;
      const offset = (t * beam.speed + beam.phase) % spacing;

      for (let dotIndex = 0; dotIndex < dotCount; dotIndex++) {
        const y = dotIndex * spacing + offset - spacing * 2;
        if (y < -18 || y > hitY + 8) continue;

        const travel = clamp(y / Math.max(hitY, 1), 0, 1);
        const alpha = beamAlpha * (0.14 + travel * 0.52) * (0.4 + focus * 0.65);
        const softSize = beam.width * (blur * 14 + 3.4 + travel * 2.2);
        const coreSize = beam.width * (focus > 0.42 ? 1.8 : 1.2);

        drawRichGlowSprite(ctx, blur > 0.5 ? sprites.haze : sprites.soft, beam.x, y, softSize, alpha * (blur > 0.45 ? 0.14 : 0.08));
        drawRichGlowSprite(ctx, sprites.core, beam.x, y, coreSize, alpha * (focus > 0.24 ? 1 : 0.6));
      }
      continue;
    }

    const fullColumnAlpha = beamAlpha * (0.022 + focus * 0.12);
    if (fullColumnAlpha > 0.008) {
      ctx.globalAlpha = fullColumnAlpha * (blur > 0.5 ? 0.45 : 0.24);
      ctx.lineWidth = beam.width * (blur * 5.8 + focus * 1.2 + 1.4);
      ctx.beginPath();
      ctx.moveTo(beam.x, -8);
      ctx.lineTo(beam.x, hitY);
      ctx.stroke();

      if (focus > 0.18) {
        ctx.globalAlpha = fullColumnAlpha;
        ctx.lineWidth = Math.max(0.55, beam.width * (0.35 + focus * 0.6));
        ctx.beginPath();
        ctx.moveTo(beam.x, -8);
        ctx.lineTo(beam.x, hitY);
        ctx.stroke();
      }
    }

    const segmentLength = Math.max(hitY * beam.length, 26);
    const segmentTop = ((t * beam.speed) + beam.phase) % (hitY + segmentLength + 24) - segmentLength;
    const segmentBottom = segmentTop + segmentLength;

    if (segmentBottom > -12 && segmentTop < hitY + 8) {
      const runT = clamp((segmentBottom + 10) / Math.max(hitY + segmentLength, 1), 0, 1);
      const segmentAlpha = beamAlpha * (0.42 + Math.sin(runT * Math.PI) * 0.58);
      ctx.globalAlpha = segmentAlpha * (blur > 0.4 ? 0.28 : 0.18);
      ctx.lineWidth = beam.width * (blur * 8.5 + focus * 1.8 + 2.8);
      ctx.beginPath();
      ctx.moveTo(beam.x, Math.max(-10, segmentTop));
      ctx.lineTo(beam.x, Math.min(hitY, segmentBottom));
      ctx.stroke();

      ctx.globalAlpha = segmentAlpha;
      ctx.lineWidth = Math.max(0.8, beam.width * (0.56 + focus * 0.86));
      ctx.beginPath();
      ctx.moveTo(beam.x, Math.max(-10, segmentTop));
      ctx.lineTo(beam.x, Math.min(hitY, segmentBottom));
      ctx.stroke();

      if (focus > 0.45) {
        drawRichGlowSprite(ctx, sprites.core, beam.x, Math.min(hitY, segmentBottom), beam.width * 1.65, segmentAlpha * 0.74);
      }
    }
  }

  ctx.restore();
  ctx.globalAlpha = 1;
}

function drawRichBackdropFloorMotion(
  ctx: CanvasRenderingContext2D,
  width: number,
  projection: RichBackdropProjection,
  lanes: RichBackdropLane[],
  sprites: RichBackdropSprites,
  timeMs: number,
  height: number,
): void {
  const t = timeMs * 0.001;

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(0, projection.horizonLeftY);
  ctx.lineTo(width, projection.horizonRightY);
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.clip();

  ctx.strokeStyle = '#ffffff';
  ctx.lineCap = 'round';

  for (const lane of lanes) {
    const startX = lane.anchorX;
    const startY = height * 1.03;
    const pulse = 0.72 + 0.28 * Math.sin(t * (1.2 + lane.speed * 1.8) + lane.phase * 6.28);
    const headT = 1 - ((t * lane.speed + lane.phase) % 1);

    if (lane.isDotted) {
      for (let dotIndex = 0; dotIndex < 8; dotIndex++) {
        const dotT = headT - dotIndex * 0.055;
        if (dotT <= 0.02 || dotT >= 1) continue;

        const x = lerp(projection.vanishX, startX, dotT);
        const y = lerp(projection.vanishY, startY, dotT);
        const alpha = lane.intensity * pulse * (0.35 + dotT * 0.55) * (1 - dotIndex * 0.06);
        const size = lane.width * (1.8 + dotT * 3.2);

        drawRichGlowSprite(ctx, sprites.soft, x, y, size * 2.6, alpha * 0.09);
        drawRichGlowSprite(ctx, sprites.core, x, y, Math.max(1.1, size), alpha * 0.88);
      }
      continue;
    }

    const frontT = clamp(headT + lane.length * 0.28, 0.04, 1);
    const backT = clamp(headT - lane.length, 0, 0.92);
    if (frontT <= backT + 0.01) continue;

    const x1 = lerp(projection.vanishX, startX, frontT);
    const y1 = lerp(projection.vanishY, startY, frontT);
    const x2 = lerp(projection.vanishX, startX, backT);
    const y2 = lerp(projection.vanishY, startY, backT);
    const alpha = lane.intensity * pulse * (0.22 + frontT * 0.68);
    const thickness = lane.width * (0.7 + frontT * 1.9);

    ctx.globalAlpha = alpha * 0.16;
    ctx.lineWidth = thickness * 4.6;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    ctx.globalAlpha = alpha;
    ctx.lineWidth = thickness;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    drawRichGlowSprite(ctx, sprites.core, x1, y1, lane.width * (1.6 + frontT * 2.4), alpha * 0.78);
  }

  ctx.restore();
  ctx.globalAlpha = 1;
}

function drawRichBackdropDust(
  ctx: CanvasRenderingContext2D,
  dust: RichBackdropDust[],
  sprites: RichBackdropSprites,
  timeMs: number,
  width: number,
  height: number,
): void {
  const t = timeMs * 0.001;

  for (const mote of dust) {
    const focus = getRichBackdropFocus(mote.depth);
    const blur = 1 - focus;
    const x = mote.x + Math.sin(t * mote.speed + mote.phase) * mote.driftX;
    const y = mote.y + Math.cos(t * (mote.speed * 0.7) + mote.phase) * mote.driftY;
    if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;

    const alpha = mote.alpha * (0.68 + 0.32 * Math.sin(t * (0.6 + mote.speed) + mote.phase));
    const size = mote.size * (0.92 + 0.18 * Math.sin(t * mote.speed + mote.phase * 1.4));
    drawRichGlowSprite(ctx, blur > 0.55 ? sprites.haze : sprites.soft, x, y, size * (blur > 0.55 ? 1.8 : 1.1), alpha * (blur > 0.45 ? 0.18 : 0.09));

    if (focus > 0.5) {
      drawRichGlowSprite(ctx, sprites.core, x, y, Math.max(1, size * 0.42), alpha * 0.85);
    }
  }

  ctx.globalAlpha = 1;
}

function drawRichBackdropScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  timeMs: number,
  scene: RichBackdropScene,
): void {
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
  ctx.drawImage(scene.staticLayer, 0, 0, width, height);
  drawRichBackdropWallMotion(ctx, width, scene.projection, scene.beams, scene.sprites, timeMs, height);
  drawRichBackdropFloorMotion(ctx, width, scene.projection, scene.lanes, scene.sprites, timeMs, height);
  drawRichBackdropDust(ctx, scene.dust, scene.sprites, timeMs, width, height);
  ctx.globalAlpha = 1;
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

const MANAGED_LOCAL_NODE_AUTH = "__managed_local_node_auth__";

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

function localNodeProxyErrorMessage(
  code: string | undefined,
  fallback: string,
  tWork?: WorkspaceMessageTranslator,
): string {
  switch (code) {
    case "endpoint-and-path-are-required":
      return tWork ? tWork("local_node_proxy_missing_params") : fallback;
    case "invalid-local-node-endpoint":
      return tWork ? tWork("local_node_proxy_invalid_endpoint") : fallback;
    case "local-node-unreachable":
      return tWork ? tWork("local_node_proxy_unreachable") : fallback;
    default:
      return fallback;
  }
}

async function readLocalNodeFailure(
  response: Response,
  fallback: string,
  tWork?: WorkspaceMessageTranslator,
): Promise<string> {
  try {
    const payload = await response.json();
    const code = typeof payload?.error === "string" ? payload.error : undefined;
    return localNodeProxyErrorMessage(code, fallback, tWork);
  } catch {
    return fallback;
  }
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const DISPLAY_REDACTED_KEYS = new Set([
  "operator_id",
  "requested_operator_id",
  "operator_identities",
  "operator_identity_count",
  "operator_namespace",
  "operator_auth_nonce_ttl_seconds",
  "operator_auth_timestamp_skew_seconds",
]);

const DISPLAY_KEY_RENAMES = new Map<string, string>([
  ["policy_tier", "access_level"],
  ["required_scopes", "required_features"],
  ["granted_scopes", "available_features"],
  ["shared_bearer_enabled", "secure_channel_enabled"],
  ["passwordless", "quick_connect_available"],
]);

const DISPLAY_VALUE_RENAMES: Record<string, string> = {
  root: "workspace",
  "local-admin": "local-workspace",
  "bridge-admin": "collaboration",
  "workflow-admin": "workflow",
  "settlement-admin": "payments",
  "trust-admin": "trust",
  "committee-member": "review",
  "did:agentcoin:local:admin": "local-workspace-session",
  "local-operator-attestation": "local-session-attestation",
};

function sanitizeDisplayValue(value: unknown, seen = new WeakSet<object>()): unknown {
  if (typeof value === "string") {
    return DISPLAY_VALUE_RENAMES[value] ?? value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeDisplayValue(item, seen));
  }

  if (!value || typeof value !== "object") {
    return value;
  }

  if (seen.has(value)) {
    return "[circular]";
  }
  seen.add(value);

  const output: Record<string, unknown> = {};
  for (const [key, rawValue] of Object.entries(value as Record<string, unknown>)) {
    if (DISPLAY_REDACTED_KEYS.has(key)) {
      continue;
    }

    const nextKey = DISPLAY_KEY_RENAMES.get(key) ?? key;
    output[nextKey] = sanitizeDisplayValue(rawValue, seen);
  }

  seen.delete(value);
  return output;
}

function prettyDisplayJson(value: unknown): string {
  return prettyJson(sanitizeDisplayValue(value));
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

type AiSubsystemCardStatus = "open" | "running" | "registered" | "attachable" | "inspect";

type AiSubsystemCard = {
  id: string;
  name: string;
  summary: string;
  glyph: string;
  status: AiSubsystemCardStatus;
  iconKey?: PreservedAiIconKey;
  icon?: ReactNode;
};

type PreservedAiIconKey = "copilot" | "claude" | "codex" | "openclaw";

function managedRegistrationBadge(registration: LocalManagedRegistration): string {
  const raw = (registration.family || registration.title || registration.type || registration.registration_id || "AGENT")
    .replace(/[^A-Za-z0-9]/g, "")
    .toUpperCase();
  return (raw || "AGT").slice(0, 3);
}

function managedRegistrationSummary(registration: LocalManagedRegistration): string {
  if (registration.preferred_integration) return registration.preferred_integration;
  if (registration.integration_candidates?.length) return registration.integration_candidates.slice(0, 3).join(" / ");
  if (registration.protocols?.length) return registration.protocols.join(" / ");
  if (registration.transport) return registration.transport;
  if (registration.type) return registration.type;
  if (registration.family) return registration.family;
  if (registration.publisher) return registration.publisher;
  return registration.registration_id;
}

function aiSubsystemSummaryForManaged(
  registration: LocalManagedRegistration,
  discovery?: LocalDiscoveryItem,
  session?: LocalAcpSession,
): string {
  if (session) {
    const sessionParts = [
      String(session.protocol || "").trim().toUpperCase(),
      String(session.transport || registration.transport || "").trim(),
    ].filter(Boolean);
    if (sessionParts.length > 0) return sessionParts.join(" / ");
  }

  if (registration.preferred_integration) return registration.preferred_integration;
  if (discovery?.agentcoin_compatibility?.preferred_integration) {
    return discovery.agentcoin_compatibility.preferred_integration;
  }
  if (registration.protocols?.length) return registration.protocols.slice(0, 3).join(" / ");
  if (discovery) return discoverySummary(discovery) || managedRegistrationSummary(registration);
  return managedRegistrationSummary(registration);
}

function aiSubsystemGlyph(primaryLabel: string, stateCode: string): string {
  const primary = (primaryLabel.replace(/[^A-Za-z0-9]/g, "").toUpperCase() || "AGT").slice(0, 3).padEnd(3, " ");
  const secondary = (stateCode.replace(/[^A-Za-z0-9]/g, "").toUpperCase() || "SYS").slice(0, 3).padEnd(3, " ");
  return ["+-----+", `| ${primary} |`, `| ${secondary} |`, "+-----+"].join("\n");
}

function aiSubsystemIdentity(...values: Array<string | undefined | null>): string {
  return values
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean)
    .join(" ");
}

function preservedAiIconKeyForIdentity(identity: string): PreservedAiIconKey | undefined {
  if (!identity) return undefined;
  if (identity.includes("openclaw")) return "openclaw";
  if (identity.includes("codex") || (identity.includes("openai") && identity.includes("code"))) return "codex";
  if ((identity.includes("github") && identity.includes("copilot")) || identity.includes("copilot")) return "copilot";
  if (identity.includes("claude") || identity.includes("anthropic")) return "claude";
  return undefined;
}

function preservedAiIconFrame(icon: ReactNode): ReactNode {
  return (
    <div className="flex h-[46px] w-[58px] shrink-0 items-center justify-center overflow-hidden rounded-sm border border-foreground/15 bg-black/45">
      {icon}
    </div>
  );
}

function preservedAiIcon(iconKey?: PreservedAiIconKey): ReactNode | null {
  if (!iconKey) return null;

  switch (iconKey) {
    case "copilot":
      return preservedAiIconFrame(
        <div className="origin-center scale-[0.72] sm:scale-[0.78]">
          <div className="flex flex-col items-center justify-center font-bold tracking-tighter bg-[#0D1117] rounded-sm shadow-inner" style={{ width: "60px", height: "60px" }}>
            <div className="flex w-full justify-between px-2">
              <div className="w-[18px] h-[18px] border-2 border-[#5FEADB] rounded-md" />
              <div className="w-[18px] h-[18px] border-2 border-[#5FEADB] rounded-md" />
            </div>
            <div className="h-[8px]" />
            <div className="flex w-full justify-between items-end h-[14px] px-2 relative">
              <div className="w-[10px] h-full bg-[#D946EF]" />
              <div className="flex gap-[6px] absolute bottom-0.5 left-1/2 -translate-x-1/2">
                <div className="w-[6px] h-[10px] bg-[#22C55E]" />
                <div className="w-[6px] h-[10px] bg-[#22C55E]" />
              </div>
              <div className="w-[10px] h-full bg-[#D946EF]" />
            </div>
            <div className="w-[44px] h-[6px] bg-[#D946EF] mt-[2px]" />
          </div>
        </div>,
      );
    case "claude":
      return preservedAiIconFrame(
        <div className="origin-center scale-[0.72] sm:scale-[0.78]">
          <div className="flex flex-col items-center justify-center font-bold tracking-tighter" style={{ width: "60px", height: "60px" }}>
            <div className="flex flex-col items-center w-[55px] drop-shadow-sm">
              <div className="w-[35px] h-[5px] bg-[#D97757]" />
              <div className="flex w-[35px] h-[5px]">
                <div className="w-[5px] h-full bg-[#D97757]" />
                <div className="w-[5px] h-full bg-[#050505]" />
                <div className="w-[15px] h-full bg-[#D97757]" />
                <div className="w-[5px] h-full bg-[#050505]" />
                <div className="w-[5px] h-full bg-[#D97757]" />
              </div>
              <div className="w-[55px] h-[5px] bg-[#D97757]" />
              <div className="w-[35px] h-[5px] bg-[#D97757]" />
              <div className="flex justify-between w-[35px] h-[10px]">
                <div className="w-[5px] h-full bg-[#D97757]" />
                <div className="w-[5px] h-full bg-[#D97757]" />
                <div className="w-[5px] h-full bg-[#D97757]" />
                <div className="w-[5px] h-full bg-[#D97757]" />
              </div>
            </div>
          </div>
        </div>,
      );
    case "codex":
      return preservedAiIconFrame(
        <div className="origin-center scale-[0.72] sm:scale-[0.78]">
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
                "0000011111100000",
              ].map((row, index) => (
                <div key={index} className="flex">
                  {row.split("").map((cell, cellIndex) => (
                    <div key={cellIndex} className={`w-[2.5px] h-[2.5px] sm:w-[3px] sm:h-[3px] ${cell === "1" ? "bg-foreground" : "bg-transparent"}`} />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>,
      );
    case "openclaw":
      return preservedAiIconFrame(
        <div className="origin-center scale-[0.72] sm:scale-[0.78]">
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
                "0000011001100000",
              ].map((row, index) => (
                <div key={index} className="flex">
                  {row.split("").map((cell, cellIndex) => (
                    <div
                      key={cellIndex}
                      className={`w-[2.5px] h-[2.5px] sm:w-[3px] sm:h-[3px] ${
                        cell === "1"
                          ? "bg-[#F2576F]"
                          : cell === "2"
                            ? "bg-white"
                            : cell === "3"
                              ? "bg-[#00A896]"
                              : "bg-transparent"
                      }`}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>,
      );
    default:
      return null;
  }
}

function terminalAgentGlyphForIconKey(iconKey?: PreservedAiIconKey): string | undefined {
  if (iconKey === "copilot") return aiSubsystemGlyph("COP", "RPL");
  if (iconKey === "codex") return aiSubsystemGlyph("CDX", "RPL");
  if (iconKey === "claude") return aiSubsystemGlyph("CLD", "RPL");
  if (iconKey === "openclaw") return aiSubsystemGlyph("CLW", "RPL");
  return undefined;
}

function terminalAgentBadgeForCard(
  card: Pick<AiSubsystemCard, "name" | "glyph" | "iconKey"> | undefined,
  fallbackLabel: string,
): Pick<TerminalHistoryEntry, "agentGlyph" | "agentName"> {
  const agentName = String(card?.name || fallbackLabel || "agent").trim() || "agent";
  return {
    agentName,
    agentGlyph: terminalAgentGlyphForIconKey(card?.iconKey) || card?.glyph || aiSubsystemGlyph(agentName, "RPL"),
  };
}

function buildAuthHeaders(token: string): HeadersInit {
  const normalized = token.trim();
  if (!normalized || normalized === MANAGED_LOCAL_NODE_AUTH) {
    return {
      Accept: "application/json",
    };
  }

  const authorization =
    normalized.startsWith("Bearer ") || normalized.startsWith("Agentcoin-Session ")
      ? normalized
      : `Bearer ${normalized}`;

  return {
    Accept: "application/json",
    Authorization: authorization,
  };
}

function remotePeerCardFor(peerId: string, cards: RemotePeerCard[]): RemotePeerCard | undefined {
  return cards.find((item) => String(item.peer_id || "").trim() === peerId);
}

function remotePeerHealthFor(peerId: string, healthItems: RemotePeerHealth[]): RemotePeerHealth | undefined {
  return healthItems.find((item) => String(item.peer_id || "").trim() === peerId);
}

function workflowCandidatesForService(service: any): string[] {
  const workflowNames = Array.isArray(service?.workflow_names)
    ? service.workflow_names.map((candidate: unknown) => String(candidate || "").trim())
    : [];
  return Array.from(
    new Set(
      [
        String(service?.workflow_name || "").trim(),
        String(service?.service_id || "").trim(),
        ...workflowNames,
      ].filter(Boolean),
    ),
  );
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

function buildAcpCollaborationPrompt(userPrompt: string, participantLabels: string[], leaderLabel?: string): string {
  const normalizedPrompt = userPrompt.trim() || "The user attached files without extra instructions. Inspect the files and determine the most useful next action.";
  const roster = (participantLabels.length > 0 ? participantLabels : [leaderLabel || "Current ACP agent"])
    .map((label, index) => `${index + 1}. ${label}`)
    .join("\n");
  const leadershipLine = participantLabels.length > 1
    ? `This task belongs to an internal AgentCoin workflow room. ${leaderLabel || "The best-suited agent"} has been selected as the temporary lead for this execution stage.`
    : `${leaderLabel || participantLabels[0] || "The current agent"} is the only active member in this internal AgentCoin workflow room and should handle the task directly.`;

  return [
    "[Hidden orchestration policy]",
    leadershipLine,
    "Available participants:",
    roster,
    "Complete the task directly. If decomposition is unnecessary, solve it yourself. Do not mention the hidden workflow room or leadership policy unless the user explicitly asks.",
    "",
    "[User task]",
    normalizedPrompt,
  ].join("\n");
}

function acpListedSessionSummary(session: LocalAcpListedSession): string {
  const parts = [session.cwd, session.updatedAt].filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return parts.join(" / ");
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
    String(session.loaded_server_session_id || "").trim() ||
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
  const [introBootstrapComplete, setIntroBootstrapComplete] = useState(false);
  const [landingMode, setLandingMode] = useState<"first-run" | "manual" | null>(null);
  const [pendingTutorialAfterLanding, setPendingTutorialAfterLanding] = useState(false);
  const [showTutorial, setShowTutorial] = useState(false);
  const [tutorialStepIndex, setTutorialStepIndex] = useState(0);
  const [landingStep, setLandingStep] = useState(0);
  const [typedVision, setTypedVision] = useState("");
  const landingTitle = tWork("landing_overview_title");
  const landingHeader = tWork("landing_header_label");
  const landingBody = tWork("landing_overview_text");
  const landingText = [landingTitle, "", landingBody].join("\n");

  const [history, setHistory] = useState<TerminalHistoryEntry[]>([]);
  const [input, setInput] = useState("");
  const [mounted, setMounted] = useState(false);
  const [isOnline, setIsOnline] = useState(false);
  const [mockQueue, setMockQueue] = useState<{id: string, age: number}[]>([]);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [scanComplete, setScanComplete] = useState(false);
  const [isAddingRemote, setIsAddingRemote] = useState(false); // Used for terminal wait mode
  const [localNodeEndpoint, setLocalNodeEndpoint] = useState("http://127.0.0.1:8080");
  const [localNodeToken, setLocalNodeToken] = useState("");
  const [localNodeBusy, setLocalNodeBusy] = useState(false);
  const [localNodeOnline, setLocalNodeOnline] = useState(false);
  const [localNodeError, setLocalNodeError] = useState("");
  const [localStatus, setLocalStatus] = useState<any>(null);
  const [localManifest, setLocalManifest] = useState<LocalManifest | null>(null);
  const [localChallengeReady, setLocalChallengeReady] = useState(false);
  const [localAttachReady, setLocalAttachReady] = useState(false);
  const [localAutoAttachEnabled, setLocalAutoAttachEnabled] = useState(true);
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
  const [localLedgerBusy, setLocalLedgerBusy] = useState(false);
  const [localLedgerError, setLocalLedgerError] = useState("");
  const [localActionBusyKey, setLocalActionBusyKey] = useState("");
  const [localMultimodalPrompt, setLocalMultimodalPrompt] = useState("");
  const [localMultimodalKind, setLocalMultimodalKind] = useState(DEFAULT_LOCAL_TASK_KIND);
  const [customLocalMultimodalKind, setCustomLocalMultimodalKind] = useState("");
  const [localMultimodalAttachments, setLocalMultimodalAttachments] = useState<LocalTaskAttachment[]>([]);
  const [localMultimodalError, setLocalMultimodalError] = useState("");
  const [localMultimodalNotice, setLocalMultimodalNotice] = useState("");
  const [showComposeTaskRouting, setShowComposeTaskRouting] = useState(false);
  const [preferCustomWorkflowTarget, setPreferCustomWorkflowTarget] = useState(false);
  const [showAcpAdvancedConfig, setShowAcpAdvancedConfig] = useState(false);
  const [selectedComposeAgentRegistrationIds, setSelectedComposeAgentRegistrationIds] = useState<string[]>([]);
  const [showWorkflowModal, setShowWorkflowModal] = useState(false);
  const [workflowModalPrompt, setWorkflowModalPrompt] = useState("");
  const [workflowModalKind, setWorkflowModalKind] = useState(DEFAULT_LOCAL_TASK_KIND);
  const [workflowModalCustomKind, setWorkflowModalCustomKind] = useState("");
  const [workflowModalAttachments, setWorkflowModalAttachments] = useState<LocalTaskAttachment[]>([]);
  const [workflowModalPreferCustomTarget, setWorkflowModalPreferCustomTarget] = useState(false);
  const [workflowModalBusyAction, setWorkflowModalBusyAction] = useState("");
  const [workflowModalError, setWorkflowModalError] = useState("");
  const [workflowModalNotice, setWorkflowModalNotice] = useState("");
  const [workflowModalResult, setWorkflowModalResult] = useState<any>(null);
  const [workflowPaymentState, setWorkflowPaymentState] = useState<WorkflowPaymentState | null>(null);
  const [walletReceiptIssueChallengeId, setWalletReceiptIssueChallengeId] = useState("");
  const [walletReceiptIssuePayer, setWalletReceiptIssuePayer] = useState("");
  const [walletReceiptIssueTxHash, setWalletReceiptIssueTxHash] = useState("");
  const [walletReceiptWorkflowName, setWalletReceiptWorkflowName] = useState("");
  const [walletReceiptDraft, setWalletReceiptDraft] = useState("");
  const [walletTokenWorkflowName, setWalletTokenWorkflowName] = useState("");
  const [walletTokenServiceId, setWalletTokenServiceId] = useState("");
  const [walletTokenMaxUses, setWalletTokenMaxUses] = useState("");
  const [walletTokenDraft, setWalletTokenDraft] = useState("");
  const [walletQueueReceiptId, setWalletQueueReceiptId] = useState("");
  const [walletQueueStatusFilter, setWalletQueueStatusFilter] = useState("");
  const [walletQueueDelaySeconds, setWalletQueueDelaySeconds] = useState("0");
  const [walletQueueMaxAttempts, setWalletQueueMaxAttempts] = useState("");
  const [walletQueueReason, setWalletQueueReason] = useState("manual-review-pending");
  const [walletRelayRpcUrl, setWalletRelayRpcUrl] = useState("");
  const [walletRelayTimeoutSeconds, setWalletRelayTimeoutSeconds] = useState("10");
  const [walletRelayRawTransactionsDraft, setWalletRelayRawTransactionsDraft] = useState("");
  const [walletActionBusyKey, setWalletActionBusyKey] = useState("");
  const [walletActionError, setWalletActionError] = useState("");
  const [walletActionNotice, setWalletActionNotice] = useState("");
  const [walletReceiptResult, setWalletReceiptResult] = useState<any>(null);
  const [walletTokenResult, setWalletTokenResult] = useState<any>(null);
  const [walletQueueItems, setWalletQueueItems] = useState<any[]>([]);
  const [walletLatestRelayRecord, setWalletLatestRelayRecord] = useState<any>(null);
  const [walletLatestFailedRelayRecord, setWalletLatestFailedRelayRecord] = useState<any>(null);
  const [walletRelayResult, setWalletRelayResult] = useState<any>(null);
  const [activeWorkspaceWindow, setActiveWorkspaceWindow] = useState<WorkspaceWindowId>("compose");
  const [pendingCriticalAction, setPendingCriticalAction] = useState<CriticalActionGuard | null>(null);
  const [criticalActionBusy, setCriticalActionBusy] = useState(false);
  const [hoveredAlertGroupId, setHoveredAlertGroupId] = useState<AlertSummaryGroupId | null>(null);
  const [isDesktopViewport, setIsDesktopViewport] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_WIDTH_DEFAULT);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarResizing, setSidebarResizing] = useState(false);

  const asciiCanvasRef = useRef<HTMLCanvasElement>(null);
  const earthAngleRef = useRef(0);
  const [earthDisplay, setEarthDisplay] = useState('');
  const radarAngleRef = useRef(0);
  const [radarDisplay, setRadarDisplay] = useState('');
  const [foundAgents, setFoundAgents] = useState<string[]>([]);
  const [checkedToJoin, setCheckedToJoin] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const landingScrollRef = useRef<HTMLDivElement>(null);
  
  const startedRun = useRef(false);
  const showLandingRef = useRef(showLanding);
  const bufferedBootHistoryRef = useRef<TerminalHistoryEntry[]>([]);
  const bootOnlinePendingRef = useRef(false);
  const bootOnlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const localProbeStartedRef = useRef(false);
  const localAutoAttachAttemptedRef = useRef("");
  const [, setTutorialLayoutTick] = useState(0);
  const sidebarRef = useRef<HTMLElement>(null);
  const sidebarWidthBeforeCollapseRef = useRef(SIDEBAR_WIDTH_DEFAULT);

  useEffect(() => {
    showLandingRef.current = showLanding;
  }, [showLanding]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (showLanding) return;
    if (!localMultimodalError && !localMultimodalNotice) return;

    const timer = window.setTimeout(() => {
      setLocalMultimodalError("");
      setLocalMultimodalNotice("");
    }, localMultimodalError ? 3200 : 1800);

    return () => {
      window.clearTimeout(timer);
    };
  }, [showLanding, localMultimodalError, localMultimodalNotice]);

  useEffect(() => {
    if (showLanding) return;
    if (selectedComposeAgentRegistrationIds.length === 0) return;

    const validRegistrationIds = new Set(localManagedRegistrations.map((item) => item.registration_id));
    const nextSelection = selectedComposeAgentRegistrationIds.filter((id) => validRegistrationIds.has(id));

    if (nextSelection.length !== selectedComposeAgentRegistrationIds.length) {
      setSelectedComposeAgentRegistrationIds(nextSelection);
    }
  }, [showLanding, localManagedRegistrations, selectedComposeAgentRegistrationIds]);

  useEffect(() => {
    if (!mounted || showLanding) return;

    const syncViewport = () => {
      setIsDesktopViewport(window.innerWidth >= DESKTOP_SIDEBAR_BREAKPOINT);
    };

    syncViewport();
    window.addEventListener("resize", syncViewport);
    return () => {
      window.removeEventListener("resize", syncViewport);
    };
  }, [mounted, showLanding]);

  useEffect(() => {
    if (!mounted || showLanding) return;

    const storedWidth = Number(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));
    if (Number.isFinite(storedWidth) && storedWidth > 0) {
      const nextWidth = clamp(Math.round(storedWidth), SIDEBAR_WIDTH_MIN, SIDEBAR_WIDTH_MAX);
      setSidebarWidth(nextWidth);
      sidebarWidthBeforeCollapseRef.current = nextWidth;
    }

    setSidebarCollapsed(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "1");
  }, [mounted, showLanding]);

  useEffect(() => {
    if (!mounted || showLanding) return;

    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, sidebarCollapsed ? "1" : "0");
  }, [mounted, showLanding, sidebarWidth, sidebarCollapsed]);

  useEffect(() => {
    if (showLanding) return;
    if (!sidebarCollapsed) {
      sidebarWidthBeforeCollapseRef.current = sidebarWidth;
    }
  }, [showLanding, sidebarWidth, sidebarCollapsed]);

  useEffect(() => {
    if (showLanding) return;
    if (!isDesktopViewport && sidebarResizing) {
      setSidebarResizing(false);
    }
  }, [showLanding, isDesktopViewport, sidebarResizing]);

  useEffect(() => {
    if (showLanding || !sidebarResizing || !isDesktopViewport) return;

    const handleMove = (event: MouseEvent) => {
      const sidebarLeft = sidebarRef.current?.getBoundingClientRect().left ?? 0;
      const dynamicMaxWidth = Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, window.innerWidth - 420));
      const nextWidth = clamp(Math.round(event.clientX - sidebarLeft), SIDEBAR_WIDTH_MIN, dynamicMaxWidth);
      setSidebarCollapsed(false);
      setSidebarWidth(nextWidth);
    };

    const stopResizing = () => {
      setSidebarResizing(false);
    };

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [showLanding, sidebarResizing, isDesktopViewport]);

  useEffect(() => {
    if (!mounted) return;

    const hasSeenIntro = window.localStorage.getItem(INTRO_STORAGE_KEY) === "1";

    if (hasSeenIntro) {
      setShowLanding(false);
      setLandingMode(null);
      setPendingTutorialAfterLanding(false);
    } else {
      setShowLanding(true);
      setLandingMode("first-run");
      setPendingTutorialAfterLanding(true);
    }

    setIntroBootstrapComplete(true);
  }, [mounted]);

  useEffect(() => {
    if (showLanding || startedRun.current) return;
    startedRun.current = true;

    const sequence: string[] = t.raw("boot_sequence");
    let delay = 0;
    const timers: ReturnType<typeof setTimeout>[] = [];
    
    sequence.forEach((msg, idx) => {
      delay += Math.random() * 200 + 100;
      timers.push(setTimeout(() => {
        const entry = { type: 'system' as const, content: msg };
        if (showLandingRef.current) {
          bufferedBootHistoryRef.current = [...bufferedBootHistoryRef.current, entry];
        } else {
          setHistory((prev) => [...prev, entry]);
        }

        if (idx === sequence.length - 1) {
          if (showLandingRef.current) {
            bootOnlinePendingRef.current = true;
          } else {
            bootOnlineTimerRef.current = setTimeout(() => setIsOnline(true), 800);
          }
        }
      }, delay));
    });

    return () => {
      timers.forEach(clearTimeout);
      if (bootOnlineTimerRef.current) {
        clearTimeout(bootOnlineTimerRef.current);
      }
    };
  }, [showLanding, t]);

  useEffect(() => {
    if (showLanding) return;

    if (bufferedBootHistoryRef.current.length > 0) {
      const bufferedEntries = bufferedBootHistoryRef.current;
      bufferedBootHistoryRef.current = [];
      setHistory((prev) => [...prev, ...bufferedEntries]);
    }

    if (bootOnlinePendingRef.current) {
      bootOnlinePendingRef.current = false;
      bootOnlineTimerRef.current = setTimeout(() => setIsOnline(true), 120);
    }

    return () => {
      if (bootOnlineTimerRef.current) {
        clearTimeout(bootOnlineTimerRef.current);
      }
    };
  }, [showLanding]);

  useEffect(() => {
    if (showLanding) return;
    if (!pendingCriticalAction) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !criticalActionBusy) {
        setPendingCriticalAction(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [showLanding, pendingCriticalAction, criticalActionBusy]);

  useEffect(() => {
    if (showLanding || !showTutorial) return;

    const syncLayout = () => {
      setTutorialLayoutTick((value) => value + 1);
    };

    syncLayout();
    window.addEventListener("resize", syncLayout);
    window.addEventListener("scroll", syncLayout, true);

    return () => {
      window.removeEventListener("resize", syncLayout);
      window.removeEventListener("scroll", syncLayout, true);
    };
  }, [showLanding, showTutorial, tutorialStepIndex, activeWorkspaceWindow]);

  useEffect(() => {
    if (showLanding || !showTutorial) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowTutorial(false);
        setTutorialStepIndex(0);
        return;
      }
      if (event.key === "ArrowRight") {
        setTutorialStepIndex((current) => Math.min(current + 1, 3));
        return;
      }
      if (event.key === "ArrowLeft") {
        setTutorialStepIndex((current) => Math.max(current - 1, 0));
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [showLanding, showTutorial]);

  useEffect(() => {
    if (USE_LEGACY_LANDING_ROUTE || !mounted || !showLanding) return;

    const canvas = asciiCanvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d', { alpha: false });
    if (!context) return;

    const frameIntervalMs = 1000 / 30;
    let rafId = 0;
    let beams = createBackdropBeams(window.innerWidth, window.innerHeight);
    let lastFrame = 0;
    let viewportWidth = window.innerWidth;
    let viewportHeight = window.innerHeight;

    const stopLoop = () => {
      if (!rafId) return;
      cancelAnimationFrame(rafId);
      rafId = 0;
    };

    const frame = (time: number) => {
      if (time - lastFrame >= frameIntervalMs) {
        drawBackdropScene(context, viewportWidth, viewportHeight, time, beams);
        lastFrame = time;
      }
      rafId = requestAnimationFrame(frame);
    };

    const startLoop = () => {
      if (rafId || document.hidden) return;
      lastFrame = 0;
      rafId = requestAnimationFrame(frame);
    };

    const resizeCanvas = () => {
      viewportWidth = window.innerWidth;
      viewportHeight = window.innerHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, _getBackdropDprCap(viewportWidth, viewportHeight));
      canvas.width = Math.floor(viewportWidth * dpr);
      canvas.height = Math.floor(viewportHeight * dpr);
      canvas.style.width = `${viewportWidth}px`;
      canvas.style.height = `${viewportHeight}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      beams = createBackdropBeams(viewportWidth, viewportHeight);
      _resetBackdropCaches();
      drawBackdropScene(context, viewportWidth, viewportHeight, performance.now(), beams);
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopLoop();
        return;
      }
      drawBackdropScene(context, viewportWidth, viewportHeight, performance.now(), beams);
      startLoop();
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    startLoop();

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('resize', resizeCanvas);
      stopLoop();
    };
  }, [mounted, showLanding]);

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

  // Global click handler to recover terminal focus if clicking on generic UI (like panel backgrounds)
  useEffect(() => {
    const handleGlobalClick = (e: MouseEvent) => {
      if (activeWorkspaceWindow !== 'compose') return;
      const target = e.target as HTMLElement;
      if (target.closest('input, textarea, button, select, label, a')) return;
      
      if (document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        inputRef.current?.focus();
      }
    };
    document.addEventListener('click', handleGlobalClick);
    return () => document.removeEventListener('click', handleGlobalClick);
  }, [activeWorkspaceWindow]);

  useEffect(() => {
    if (showLanding || activeWorkspaceWindow !== 'compose') return;

    const focusTimer = window.setTimeout(() => {
      inputRef.current?.focus();
    }, 50);

    return () => clearTimeout(focusTimer);
  }, [activeWorkspaceWindow, showLanding]);

  useEffect(() => {
    if (showLanding || localProbeStartedRef.current) return;
    localProbeStartedRef.current = true;
    void probeLocalNode();
  }, [showLanding]);

  useEffect(() => {
    if (
      showLanding ||
      !localAutoAttachEnabled ||
      !localNodeOnline ||
      localAttachReady ||
      localNodeBusy ||
      localDiscoveryBusy
    ) {
      return;
    }

    const endpointKey = normalizeNodeEndpoint(localNodeEndpoint);
    if (!endpointKey || localAutoAttachAttemptedRef.current === endpointKey) return;

    localAutoAttachAttemptedRef.current = endpointKey;
    void handleAttachLocalNode();
  }, [showLanding, localAutoAttachEnabled, localNodeOnline, localAttachReady, localNodeBusy, localDiscoveryBusy, localNodeEndpoint]);

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

  useEffect(() => {
    const receiptId = String(serviceUsageReconciliation?.receipt_id || paymentOpsSummary?.receipt_id || "").trim();
    const workflowName = String(serviceUsageReconciliation?.workflow_name || "").trim();
    const serviceId = String(serviceUsageReconciliation?.service_id || "").trim();

    if (receiptId) {
      setWalletQueueReceiptId((prev) => prev || receiptId);
    }
    if (workflowName) {
      setWalletReceiptWorkflowName((prev) => prev || workflowName);
      setWalletTokenWorkflowName((prev) => prev || workflowName);
    }
    if (serviceId) {
      setWalletTokenServiceId((prev) => prev || serviceId);
    }
  }, [paymentOpsSummary?.receipt_id, serviceUsageReconciliation?.receipt_id, serviceUsageReconciliation?.service_id, serviceUsageReconciliation?.workflow_name]);

  async function probeLocalNode(overrideEndpoint?: string) {
    const baseUrl = normalizeNodeEndpoint(overrideEndpoint ?? localNodeEndpoint);
    if (!baseUrl) return;

    setLocalAutoAttachEnabled(true);
    localAutoAttachAttemptedRef.current = "";
    setLocalNodeBusy(true);
    setLocalNodeError("");

    try {
      const statusResponse = await fetchLocalNode(baseUrl, "/v1/status");

      if (!statusResponse.ok) {
        throw new Error(await readLocalNodeFailure(statusResponse, tWork("local_node_unavailable"), tWork));
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
      setLocalNodeToken("");
      setLocalStatus(null);
      setLocalManifest(null);
      setLocalChallengeReady(false);
      setLocalAttachReady(false);
      setLocalDiscoveryItems([]);
      setLocalManagedRegistrations([]);
      setLocalAcpSessions([]);
      setLocalAcpBoundary(null);
      setLocalTasks([]);
      setLocalServices([]);
      setLocalCapabilities([]);
      setPaymentOpsSummary(null);
      setServiceUsageSummary(null);
      setServiceUsageReconciliation(null);
      setRenterTokenSummary(null);
      setLocalSessionTaskInputs({});
      setLocalRuntimeError("");
      setLocalLedgerError("");
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
      throw new Error(await readLocalNodeFailure(response, tWork("local_node_discovery_failed"), tWork));
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
      throw new Error(await readLocalNodeFailure(firstFailure, tWork("remote_peers_error"), tWork));
    }

    const peersPayload = await peersResponse.json();
    const cardsPayload = await cardsResponse.json();
    const healthPayload = await healthResponse.json();

    setRemotePeers(Array.isArray(peersPayload?.items) ? peersPayload.items : []);
    setRemotePeerCards(Array.isArray(cardsPayload?.items) ? cardsPayload.items : []);
    setRemotePeerHealth(Array.isArray(healthPayload?.items) ? healthPayload.items : []);
  }

  async function fetchLocalAgentRuntimeState(token: string): Promise<LocalRuntimeSnapshot> {
    const headers = buildAuthHeaders(token);
    const [managedResponse, acpResponse, tasksResponse] = await Promise.all([
      fetchLocalNode(localNodeEndpoint, "/v1/discovery/local-agents/managed", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/discovery/local-agents/acp-sessions", { headers }),
      fetchLocalNode(localNodeEndpoint, "/v1/tasks", { headers: { Accept: "application/json" } }),
    ]);

    if (!managedResponse.ok || !acpResponse.ok) {
      const firstFailure = !managedResponse.ok ? managedResponse : acpResponse;
      throw new Error(await readLocalNodeFailure(firstFailure, tWork("local_runtime_error"), tWork));
    }

    const managedPayload = await managedResponse.json();
    const acpPayload = await acpResponse.json();
    const managedRegistrations = Array.isArray(managedPayload?.items) ? managedPayload.items : [];
    const acpSessions = Array.isArray(acpPayload?.items) ? acpPayload.items : [];
    const acpBoundary = acpPayload?.protocol_boundary ? acpPayload.protocol_boundary : null;
    let tasks: LocalTaskItem[] = [];

    setLocalManagedRegistrations(managedRegistrations);
    setLocalAcpSessions(acpSessions);
    setLocalAcpBoundary(acpBoundary);
    if (tasksResponse.ok) {
      const tasksPayload = await tasksResponse.json();
      tasks = Array.isArray(tasksPayload?.items) ? tasksPayload.items : [];
      setLocalTasks(tasks);
    } else {
      setLocalTasks([]);
    }

    return {
      managedRegistrations,
      acpSessions,
      acpBoundary,
      tasks,
    };
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

  async function refreshLedgerState() {
    if (!localNodeOnline) {
      setLocalLedgerError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setLocalLedgerError(tWork("local_node_auth_needed"));
      return;
    }

    setLocalLedgerBusy(true);
    setLocalLedgerError("");

    try {
      await fetchPaymentAndServiceState(localNodeToken);
    } catch (error) {
      setLocalLedgerError(error instanceof Error ? error.message : tWork("wallet_refresh_failed"));
    } finally {
      setLocalLedgerBusy(false);
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
      throw new Error(await readLocalNodeFailure(response, tWork("local_action_failed"), tWork));
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

  function handleClearComposeAttachments() {
    setLocalMultimodalAttachments([]);
    setLocalMultimodalError("");
    setLocalMultimodalNotice(tWork("local_multimodal_clear_success"));
  }

  function handleDisconnectLocalNode() {
    setActiveWorkspaceWindow("node");
    setLocalAutoAttachEnabled(false);
    localAutoAttachAttemptedRef.current = normalizeNodeEndpoint(localNodeEndpoint);
    setLocalNodeToken("");
    setLocalAttachReady(false);
    setLocalDiscoveryItems([]);
    setCheckedToJoin([]);
    setIsDiscovering(false);
    setScanComplete(false);
    setRemotePeers([]);
    setRemotePeerCards([]);
    setRemotePeerHealth([]);
    setRemotePeersError("");
    setLocalManagedRegistrations([]);
    setLocalAcpSessions([]);
    setLocalAcpBoundary(null);
    setLocalTasks([]);
    setLocalServices([]);
    setLocalCapabilities([]);
    setPaymentOpsSummary(null);
    setServiceUsageSummary(null);
    setServiceUsageReconciliation(null);
    setRenterTokenSummary(null);
    setLocalSessionTaskInputs({});
    setLocalRuntimeError("");
    setLocalLedgerError("");
    setLocalNodeError("");
    setHistory((prev) => [...prev, { type: 'system', content: tWork("disconnect_success") }]);
  }

  function openStopRegistrationGuard(registration: LocalManagedRegistration) {
    setPendingCriticalAction({
      type: "stop-registration",
      windowId: "node",
      registrationId: registration.registration_id,
      registrationLabel: registration.title || registration.registration_id,
    });
  }

  function openCloseAcpSessionGuard(session: LocalAcpSession, registration?: LocalManagedRegistration) {
    setPendingCriticalAction({
      type: "close-acp-session",
      windowId: "node",
      sessionId: session.session_id,
      registrationId: session.registration_id,
      registrationLabel: registration?.title || session.registration_id,
    });
  }

  function openClearComposeAttachmentsGuard() {
    setPendingCriticalAction({
      type: "clear-compose-attachments",
      windowId: "compose",
      attachmentCount: localMultimodalAttachments.length,
    });
  }

  function openDisconnectLocalNodeGuard() {
    setPendingCriticalAction({
      type: "disconnect-local-node",
      windowId: "node",
      registrationCount: localManagedRegistrations.length,
      sessionCount: localAcpSessions.length,
      catalogCount: localServices.length + localCapabilities.length,
    });
  }

  async function confirmCriticalActionGuard() {
    if (!pendingCriticalAction || criticalActionBusy) return;

    const action = pendingCriticalAction;
    setCriticalActionBusy(true);

    try {
      if (action.type === "stop-registration") {
        const registration = localManagedRegistrations.find((item) => item.registration_id === action.registrationId);
        if (!registration) {
          setLocalRuntimeError(tWork("local_action_failed"));
          return;
        }
        await handleStopRegistration(registration);
        return;
      }

      if (action.type === "clear-compose-attachments") {
        handleClearComposeAttachments();
        return;
      }

      if (action.type === "disconnect-local-node") {
        handleDisconnectLocalNode();
        return;
      }

      const session = localAcpSessions.find((item) => item.session_id === action.sessionId);
      if (!session) {
        setLocalRuntimeError(tWork("local_acp_action_failed"));
        return;
      }
      await handleCloseAcpSession(session);
    } finally {
      setCriticalActionBusy(false);
      setPendingCriticalAction(null);
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

  async function handleListAcpServerSessions(session: LocalAcpSession) {
    setLocalActionBusyKey(`list-sessions:${session.session_id}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/list", {
        session_id: session.session_id,
        dispatch: true,
      });
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_acp_session_list_success") }]);
    } catch {
      setLocalRuntimeError(tWork("local_acp_action_failed"));
    } finally {
      setLocalActionBusyKey("");
    }
  }

  async function handleLoadAcpServerSession(session: LocalAcpSession, serverSessionId: string) {
    const normalizedServerSessionId = serverSessionId.trim();
    if (!normalizedServerSessionId) {
      setLocalRuntimeError(tWork("local_acp_task_fields_required"));
      return;
    }

    setLocalActionBusyKey(`load-session:${session.session_id}:${normalizedServerSessionId}`);
    setLocalRuntimeError("");

    try {
      await postLocalAction("/v1/discovery/local-agents/acp-session/load", {
        session_id: session.session_id,
        server_session_id: normalizedServerSessionId,
        dispatch: true,
      });
      setLocalSessionTaskInputs((prev) => ({
        ...prev,
        [session.session_id]: {
          taskId: prev[session.session_id]?.taskId || session.last_task_request_intent?.mapping?.agentcoin_task_id || "",
          serverSessionId: normalizedServerSessionId,
        },
      }));
      await fetchLocalAgentRuntimeState(localNodeToken);
      setHistory((prev) => [
        ...prev,
        { type: 'system', content: tWork("local_acp_session_load_success", { sessionId: normalizedServerSessionId }) },
      ]);
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

  async function loadMultimodalAttachments(files: File[]): Promise<LocalTaskAttachment[]> {
    return Promise.all(
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
      const nextAttachments = await loadMultimodalAttachments(files);
      setLocalMultimodalAttachments((prev) => [...prev, ...nextAttachments]);
    } catch (error) {
      setLocalMultimodalError(error instanceof Error ? error.message : tWork("local_multimodal_dispatch_failed"));
    }
  }

  async function handleWorkflowModalFilesSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";

    if (files.length === 0) return;

    setWorkflowModalError("");
    setWorkflowModalNotice("");

    if (workflowModalAttachments.length + files.length > MAX_MULTIMODAL_FILES) {
      setWorkflowModalError(
        tWork("local_multimodal_attachment_limit", {
          count: MAX_MULTIMODAL_FILES,
          sizeMb: String(MAX_MULTIMODAL_FILE_BYTES / (1024 * 1024)),
        }),
      );
      return;
    }

    try {
      const nextAttachments = await loadMultimodalAttachments(files);
      setWorkflowModalAttachments((prev) => [...prev, ...nextAttachments]);
    } catch (error) {
      setWorkflowModalError(error instanceof Error ? error.message : tWork("local_multimodal_dispatch_failed"));
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

    const selectedTargets = selectedComposeAgentRegistrationIds
      .map((registrationId) => {
        const registration = localManagedRegistrations.find((item) => item.registration_id === registrationId);
        if (!registration) return null;

        const card = aiSubsystemCardsById.get(registrationId);
        return {
          registrationId,
          label: card?.name || registration.title || registrationId,
        };
      })
      .filter((item): item is { registrationId: string; label: string } => Boolean(item));

    const availableTargets = localManagedRegistrations
      .filter((item) => String(item.status || "").trim().toLowerCase() !== "closed")
      .map((registration) => {
        const card = aiSubsystemCardsById.get(registration.registration_id);
        return {
          registrationId: registration.registration_id,
          label: card?.name || registration.title || registration.registration_id,
        };
      });

    const collaborationTargets = selectedTargets.length > 0 ? selectedTargets : availableTargets;

    if (selectedComposeAgentRegistrationIds.length > 0 && collaborationTargets.length === 0) {
      setLocalMultimodalError(tWork("ai_subsystem_selection_invalid"));
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

      const collaborationRegistrationIds = collaborationTargets.map((item) => item.registrationId);
      const previewSnapshot: LocalRuntimeSnapshot = {
        managedRegistrations: localManagedRegistrations,
        acpSessions: localAcpSessions,
        acpBoundary: localAcpBoundary,
        tasks: localTasks,
      };
      const previewLeader = collaborationRegistrationIds.length > 0
        ? selectAutoAcpTarget(previewSnapshot, collaborationRegistrationIds)
        : null;
      const previewLeaderLabel = previewLeader
        ? aiSubsystemCardsById.get(previewLeader.registration.registration_id)?.name || previewLeader.registration.title || previewLeader.registration.registration_id
        : collaborationTargets[0]?.label || "";
      const collaborationPrompt = collaborationTargets.length > 0
        ? buildAcpCollaborationPrompt(promptText, collaborationTargets.map((item) => item.label), previewLeaderLabel)
        : "";
      const workflowRoomPayload = collaborationTargets.length > 0
        ? {
            kind: "workflow-room",
            ux_mode: "simple-default",
            leadership_mode: "soft",
            leader_strategy: "auto-elect",
            selection_mode: selectedTargets.length > 0 ? "explicit" : "auto-all",
            participant_registration_ids: collaborationRegistrationIds,
            participant_labels: collaborationTargets.map((item) => item.label),
            provisional_leader_registration_id: previewLeader?.registration.registration_id,
            provisional_leader_label: previewLeaderLabel || undefined,
          }
        : undefined;

      const dispatchTask = async (): Promise<string> => {
        const response = await fetchLocalNode(localNodeEndpoint, "/v1/tasks/dispatch", {
          method: "POST",
          headers: {
            ...buildAuthHeaders(localNodeToken),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            kind: localMultimodalKind.trim() || DEFAULT_LOCAL_TASK_KIND,
            role: "worker",
            prefer_local: true,
            payload: {
              input: {
                prompt: promptText,
                attachments: attachmentsPayload,
              },
              attachments: attachmentsPayload,
              ...(workflowRoomPayload ? { _workflow_room: workflowRoomPayload } : {}),
              _runtime: {
                prompt: promptText,
                ...(collaborationTargets.length > 0
                  ? {
                      acp_prompt: collaborationPrompt,
                      collaboration: {
                        mode: "workflow-room",
                        leadership_mode: "soft",
                        leader_strategy: "auto-elect",
                        selection_mode: selectedTargets.length > 0 ? "explicit" : "auto-all",
                        participant_registration_ids: collaborationRegistrationIds,
                        participant_labels: collaborationTargets.map((item) => item.label),
                        elected_leader_registration_id: previewLeader?.registration.registration_id,
                        elected_leader_label: previewLeaderLabel || undefined,
                      },
                    }
                  : {}),
              },
              multimodal: true,
            },
          }),
        });

        if (!response.ok) {
          throw new Error(await readLocalNodeFailure(response, tWork("local_multimodal_dispatch_failed"), tWork));
        }

        const created = await response.json();
        const createdTaskId = String(created?.task?.id || "").trim();

        if (!createdTaskId) {
          throw new Error(tWork("local_multimodal_dispatch_failed"));
        }

        return createdTaskId;
      };

      const createdTaskId = await dispatchTask();

      await fetchLocalAgentRuntimeState(localNodeToken);

      setLocalMultimodalPrompt("");
      setLocalMultimodalKind(DEFAULT_LOCAL_TASK_KIND);
      setPreferCustomWorkflowTarget(false);
      setShowComposeTaskRouting(false);
      setLocalMultimodalAttachments([]);
      const successMessage = collaborationTargets.length > 0
        ? tWork("local_multimodal_dispatch_room_success", { id: createdTaskId || "-" })
        : tWork("local_multimodal_dispatch_success", { id: createdTaskId || "-" });
      setLocalMultimodalNotice(successMessage);
      setHistory((prev) => [...prev, { type: 'system', content: successMessage }]);

      void autoRouteTaskThroughAcp(createdTaskId, collaborationTargets.length > 0
        ? {
            preferredRegistrationId: previewLeader?.registration.registration_id,
            allowedRegistrationIds: collaborationRegistrationIds,
            memberLabels: collaborationTargets.map((item) => item.label),
          }
        : undefined);
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
        throw new Error(await readLocalNodeFailure(response, tWork("remote_peers_sync_failed"), tWork));
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

    const didLoadAny = [
      servicesResponse.ok,
      capabilitiesResponse.ok,
      paymentOpsResponse.ok,
      serviceUsageResponse.ok,
      serviceReconResponse.ok,
      renterTokenResponse.ok,
    ].some(Boolean);

    if (servicesResponse.ok) {
      const data = await (servicesResponse as Response).json();
      setLocalServices(Array.isArray(data) ? data : data.services || []);
    } else {
      setLocalServices([]);
    }
    if (capabilitiesResponse.ok) {
      const data = await (capabilitiesResponse as Response).json();
      setLocalCapabilities(Array.isArray(data) ? data : data.capabilities || []);
    } else {
      setLocalCapabilities([]);
    }
    if (paymentOpsResponse.ok) {
      setPaymentOpsSummary(await (paymentOpsResponse as Response).json());
    } else {
      setPaymentOpsSummary(null);
    }
    if (serviceUsageResponse.ok) {
      setServiceUsageSummary(await (serviceUsageResponse as Response).json());
    } else {
      setServiceUsageSummary(null);
    }
    if (serviceReconResponse.ok) {
      setServiceUsageReconciliation(await (serviceReconResponse as Response).json());
    } else {
      setServiceUsageReconciliation(null);
    }
    if (renterTokenResponse.ok) {
      setRenterTokenSummary(await (renterTokenResponse as Response).json());
    } else {
      setRenterTokenSummary(null);
    }

    if (!didLoadAny) {
      throw new Error(tWork("wallet_refresh_failed"));
    }
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
           throw new Error(tWork("network_timeout_error"));
        }
        throw new Error(
          tWork("network_transport_error", {
            details: String(err.message || tWork("network_unknown_detail")),
          }),
        );
      }
    }
    throw new Error(tWork("network_unreachable_state"));
  }

  async function handleVerifyAuth(challengeId: string, principal: string, publicKey: string) {
    if (!challengeId || challengeId.length > 256 || !principal || !publicKey) {
      throw new Error(tWork("security_invalid_auth_payload"));
    }
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, "/v1/auth/verify"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: challengeId, principal, public_key: publicKey }),
    });
    if (!response.ok) {
       const err = await response.text();
       throw new Error(
         tWork("auth_verify_failed", {
           status: response.status,
           details: err.slice(0, 100),
         }),
       );
    }
    return await response.json();
  }

  async function handleWorkflowExecute(
    workflowName: string,
    inputData: any,
    paymentContext: {
      payer?: string;
      paymentReceipt?: any;
      renterToken?: any;
      taskId?: string;
    } = {},
  ): Promise<WorkflowExecuteOutcome> {
    if (!workflowName || typeof workflowName !== 'string' || workflowName.length > 128) {
      throw new Error(tWork("security_invalid_workflow_name"));
    }
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, "/v1/workflow/execute"), {
      method: "POST",
      headers: { ...buildAuthHeaders(localNodeToken), "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow_name: workflowName,
        input: inputData,
        payer: paymentContext.payer,
        payment_receipt: paymentContext.paymentReceipt,
        renter_token: paymentContext.renterToken,
        task_id: paymentContext.taskId,
      }),
    });
    
    if (response.status === 402) {
      const paymentRequiredJson = await response.json().catch(() => null);
      const paymentHeader = response.headers.get("X-Agentcoin-Payment-Required") || "";
      let quoteDetails = paymentHeader;
      if (paymentRequiredJson?.payment?.quote) {
         quoteDetails = JSON.stringify(paymentRequiredJson.payment.quote);
      }
      return {
        status: "payment-required",
        payload: {
          payment: paymentRequiredJson?.payment || null,
          quoteDetails,
        },
      };
    } else if (response.status === 401 || response.status === 403) {
      throw new Error(tWork("workflow_access_denied"));
    } else if (!response.ok) {
      const errText =
        (await response.text().catch(() => tWork("network_unknown_detail"))).trim() ||
        tWork("network_unknown_detail");
      throw new Error(
        tWork("workflow_execution_failed", {
          status: response.status,
          details: errText.slice(0, 150),
        }),
      );
    }
    return {
      status: "accepted",
      payload: await response.json(),
    };
  }

  async function handleRenterTokenOperations(action: 'issue' | 'introspect', payload: any) {
    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, `/v1/payments/renter-tokens/${action}`), {
      method: "POST",
      headers: { ...buildAuthHeaders(localNodeToken), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
       const errText = await response.text();
       throw new Error(
         tWork("renter_token_operation_failed", {
           action: action === "issue" ? tWork("payment_action_issue") : tWork("payment_action_introspect"),
           details: errText.slice(0, 100),
         }),
       );
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
       throw new Error(
         tWork("receipt_operation_failed", {
           action: action === "issue" ? tWork("payment_action_issue") : tWork("payment_action_introspect"),
           details: errText.slice(0, 100),
         }),
       );
    }
    return await response.json();
  }

  async function handleAttachLocalNode() {
    if (!localNodeOnline) {
      setLocalNodeError(tWork("local_node_unavailable"));
      return;
    }

    setLocalDiscoveryBusy(true);
    setLocalNodeError("");
    setLocalRuntimeError("");

    try {
      const items = await fetchLocalDiscoveryItems(localNodeToken);
      setLocalNodeToken(MANAGED_LOCAL_NODE_AUTH);
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
      if (extendedStateResult.status === "rejected") {
        setLocalLedgerError(tWork("wallet_refresh_failed"));
      } else {
        setLocalLedgerError("");
      }
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_attach_success") }]);
    } catch {
      setLocalNodeToken("");
      setLocalAttachReady(false);
      setLocalServices([]);
      setLocalCapabilities([]);
      setPaymentOpsSummary(null);
      setServiceUsageSummary(null);
      setServiceUsageReconciliation(null);
      setRenterTokenSummary(null);
      setLocalLedgerError("");
      setLocalNodeError(tWork("local_node_attach_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_attach_failed") }]);
    } finally {
      setLocalDiscoveryBusy(false);
    }
  }

  async function handleDiscoverAgents() {
    if (!localNodeOnline) {
      setLocalNodeError(tWork("local_node_unavailable"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_unavailable") }]);
      return;
    }

    setLocalDiscoveryBusy(true);
    setLocalNodeError("");
    setLocalRuntimeError("");

    try {
      const items = await fetchLocalDiscoveryItems(localNodeToken);
      setLocalNodeToken(MANAGED_LOCAL_NODE_AUTH);
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
      if (extendedStateResult.status === "rejected") {
        setLocalLedgerError(tWork("wallet_refresh_failed"));
      } else {
        setLocalLedgerError("");
      }
      setScanComplete(false);
      setIsDiscovering(true);
      setHistory((prev) => [
        ...prev,
        { type: 'system', content: tWork("local_node_discovery_summary", { count: items.length }) },
      ]);
    } catch {
      setLocalNodeToken("");
      setIsDiscovering(false);
      setLocalAttachReady(false);
      setLocalServices([]);
      setLocalCapabilities([]);
      setPaymentOpsSummary(null);
      setServiceUsageSummary(null);
      setServiceUsageReconciliation(null);
      setRenterTokenSummary(null);
      setLocalLedgerError("");
      setLocalNodeError(tWork("local_node_discovery_failed"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("local_node_discovery_failed") }]);
    } finally {
      setLocalDiscoveryBusy(false);
    }
  }

  function openWorkflowModal() {
    const workflowOptions = localServices.flatMap((service: any) => workflowCandidatesForService(service));
    const initialWorkflow = workflowOptions[0] || DEFAULT_LOCAL_TASK_KIND;
    setActiveWorkspaceWindow("swarm");
    setWorkflowModalKind(initialWorkflow);
    setWorkflowModalCustomKind("");
    setWorkflowModalPreferCustomTarget(false);
    setWorkflowModalPrompt("");
    setWorkflowModalAttachments([]);
    setWorkflowModalError("");
    setWorkflowModalNotice("");
    setWorkflowModalResult(null);
    setWorkflowPaymentState(null);
    setShowWorkflowModal(true);
  }

  async function executeWorkflowFromModal(overrides: { paymentReceipt?: any; renterToken?: any } = {}) {
    if (!localNodeOnline) {
      setWorkflowModalError(tWork("local_node_unavailable"));
      return;
    }
    if (!localNodeToken.trim()) {
      setWorkflowModalError(tWork("local_node_auth_needed"));
      return;
    }

    const workflowName = String(workflowModalKind || "").trim();
    const trimmedPrompt = workflowModalPrompt.trim();
    if (!workflowName) {
      setWorkflowModalError(tWork("security_invalid_workflow_name"));
      return;
    }
    if (!trimmedPrompt && workflowModalAttachments.length === 0) {
      setWorkflowModalError(tWork("local_multimodal_dispatch_required"));
      return;
    }

    setWorkflowModalBusyAction("execute");
    setWorkflowModalError("");
    setWorkflowModalNotice("");

    try {
      const outcome = await handleWorkflowExecute(
        workflowName,
        {
          prompt: trimmedPrompt,
          attachments: workflowModalAttachments,
        },
        {
          payer: workflowPaymentState?.payer || undefined,
          paymentReceipt: overrides.paymentReceipt ?? workflowPaymentState?.receipt ?? undefined,
          renterToken: overrides.renterToken ?? workflowPaymentState?.renterToken ?? undefined,
        },
      );

      if (outcome.status === "payment-required") {
        const notice = tWork("workflow_payment_required", { quote: outcome.payload.quoteDetails || "-" });
        setWorkflowPaymentState((prev) => ({
          payment: outcome.payload.payment,
          quoteDetails: outcome.payload.quoteDetails,
          payer: prev?.payer || "",
          txHash: prev?.txHash || "",
          receipt: null,
          receiptAttestation: null,
          renterToken: null,
        }));
        setWorkflowModalResult(null);
        setWorkflowModalNotice(notice);
        setHistory((prev) => [...prev, { type: 'system', content: notice }]);
        return;
      }

      const acceptedTaskId = String(outcome.payload?.task?.id || "").trim();
      const notice = tWork("workflow_task_accepted", { id: acceptedTaskId || "-" });
      setWorkflowModalResult(outcome.payload);
      setWorkflowModalNotice(notice);
      setHistory((prev) => [...prev, { type: 'system', content: notice }]);
      await Promise.allSettled([
        fetchLocalAgentRuntimeState(localNodeToken),
        fetchPaymentAndServiceState(localNodeToken),
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWorkflowModalError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWorkflowModalBusyAction("");
    }
  }

  async function issueWorkflowReceipt() {
    const challengeId = String(workflowPaymentState?.payment?.challenge?.challenge_id || "").trim();
    const payer = String(workflowPaymentState?.payer || "").trim();
    const txHash = String(workflowPaymentState?.txHash || "").trim();
    if (!challengeId || !payer || !txHash) {
      setWorkflowModalError(tWork("workflow_receipt_fields_required"));
      return;
    }

    setWorkflowModalBusyAction("issue-receipt");
    setWorkflowModalError("");
    setWorkflowModalNotice("");

    try {
      const issued = await handleReceiptOperations("issue", {
        challenge_id: challengeId,
        payer,
        tx_hash: txHash,
      });
      setWorkflowPaymentState((prev) => prev ? {
        ...prev,
        receipt: issued?.receipt || null,
        receiptAttestation: issued?.attestation || null,
      } : prev);
      const notice = tWork("workflow_receipt_issue_success");
      setWorkflowModalNotice(notice);
      setHistory((prev) => [...prev, { type: 'system', content: notice }]);
      await fetchPaymentAndServiceState(localNodeToken).catch(() => undefined);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWorkflowModalError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWorkflowModalBusyAction("");
    }
  }

  async function issueWorkflowRenterToken() {
    const workflowName = String(workflowModalKind || "").trim();
    if (!workflowPaymentState?.receipt) {
      setWorkflowModalError(tWork("workflow_receipt_required"));
      return;
    }

    const serviceId = String(
      localServices.find((service: any) => workflowCandidatesForService(service).includes(workflowName))?.service_id || "",
    ).trim();

    setWorkflowModalBusyAction("issue-token");
    setWorkflowModalError("");
    setWorkflowModalNotice("");

    try {
      const issued = await handleRenterTokenOperations("issue", {
        payment_receipt: workflowPaymentState.receipt,
        workflow_name: workflowName,
        service_id: serviceId || undefined,
      });
      setWorkflowPaymentState((prev) => prev ? {
        ...prev,
        renterToken: issued?.token || issued?.renter_token || issued,
      } : prev);
      const notice = tWork("workflow_renter_token_issue_success");
      setWorkflowModalNotice(notice);
      setHistory((prev) => [...prev, { type: 'system', content: notice }]);
      await fetchPaymentAndServiceState(localNodeToken).catch(() => undefined);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWorkflowModalError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWorkflowModalBusyAction("");
    }
  }

  function parseWalletJsonDraft(text: string, invalidMessage: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      throw new Error(invalidMessage);
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(invalidMessage);
      }
      return parsed;
    } catch {
      throw new Error(invalidMessage);
    }
  }

  function tryParseWalletJsonDraft(text: string): any | null {
    const trimmed = text.trim();
    if (!trimmed) {
      return null;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }

  function parseWalletJsonArrayDraft(text: string, invalidMessage: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      throw new Error(invalidMessage);
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!Array.isArray(parsed)) {
        throw new Error(invalidMessage);
      }
      return parsed;
    } catch {
      throw new Error(invalidMessage);
    }
  }

  function currentWalletReceiptId(): string {
    const draft = tryParseWalletJsonDraft(walletReceiptDraft);
    return String(
      walletQueueReceiptId ||
      draft?.receipt_id ||
      serviceUsageReconciliation?.receipt_id ||
      paymentOpsSummary?.receipt_id ||
      renterTokenSummary?.receipt_id ||
      "",
    ).trim();
  }

  function currentWalletWorkflowName(receipt?: any): string {
    return String(
      receipt?.workflow_name ||
      walletReceiptWorkflowName ||
      walletTokenWorkflowName ||
      serviceUsageReconciliation?.workflow_name ||
      paymentOpsSummary?.service_usage_reconciliation?.workflow_name ||
      "",
    ).trim();
  }

  function currentWalletServiceId(workflowName?: string): string {
    const directServiceId = String(
      walletTokenServiceId ||
      serviceUsageReconciliation?.service_id ||
      "",
    ).trim();
    if (directServiceId) {
      return directServiceId;
    }

    const normalizedWorkflowName = String(workflowName || currentWalletWorkflowName()).trim();
    if (!normalizedWorkflowName) {
      return "";
    }

    return String(
      localServices.find((service: any) => workflowCandidatesForService(service).includes(normalizedWorkflowName))?.service_id || "",
    ).trim();
  }

  function parsedWalletQueueDelaySeconds(): number {
    const parsed = Number(walletQueueDelaySeconds.trim() || 0);
    return Number.isFinite(parsed) && parsed >= 0 ? Math.trunc(parsed) : 0;
  }

  function parsedWalletQueueMaxAttempts(): number | undefined {
    const parsed = Number(walletQueueMaxAttempts.trim());
    return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : undefined;
  }

  function parsedWalletRelayTimeoutSeconds(): number {
    const parsed = Number(walletRelayTimeoutSeconds.trim() || 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 10;
  }

  function setWalletReceiptContext(receipt: any, workflowName?: string, serviceId?: string) {
    if (receipt && typeof receipt === "object" && !Array.isArray(receipt)) {
      setWalletReceiptDraft(prettyJson(receipt));
    }

    const nextReceiptId = String(receipt?.receipt_id || currentWalletReceiptId()).trim();
    const nextWorkflowName = String(workflowName || currentWalletWorkflowName(receipt)).trim();
    const nextServiceId = String(serviceId || currentWalletServiceId(nextWorkflowName)).trim();

    if (nextReceiptId) {
      setWalletQueueReceiptId(nextReceiptId);
    }
    if (nextWorkflowName) {
      setWalletReceiptWorkflowName(nextWorkflowName);
      setWalletTokenWorkflowName((prev) => prev || nextWorkflowName);
    }
    if (nextServiceId) {
      setWalletTokenServiceId((prev) => prev || nextServiceId);
    }
  }

  async function readWalletActionFailure(response: Response): Promise<string> {
    const raw = (await response.text().catch(() => "")).trim();
    if (!raw) {
      return String(response.status || tWork("local_action_failed"));
    }
    try {
      const payload = JSON.parse(raw);
      if (typeof payload?.error === "string" && payload.error.trim()) {
        return payload.error.trim();
      }
    } catch {
      return raw.slice(0, 180);
    }
    return raw.slice(0, 180);
  }

  async function walletGetJson(path: string) {
    if (!localNodeOnline) {
      throw new Error(tWork("local_node_unavailable"));
    }
    if (!localNodeToken.trim()) {
      throw new Error(tWork("local_node_auth_needed"));
    }

    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, path), {
      headers: buildAuthHeaders(localNodeToken),
    });

    if (!response.ok) {
      throw new Error(await readWalletActionFailure(response));
    }

    return await response.json();
  }

  async function walletPostJson(path: string, payload: any) {
    if (!localNodeOnline) {
      throw new Error(tWork("local_node_unavailable"));
    }
    if (!localNodeToken.trim()) {
      throw new Error(tWork("local_node_auth_needed"));
    }

    const response = await resilientFetch(buildLocalNodeProxyUrl(localNodeEndpoint, path), {
      method: "POST",
      headers: {
        ...buildAuthHeaders(localNodeToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(await readWalletActionFailure(response));
    }

    return await response.json();
  }

  async function resolveWalletReceiptContext(receiptIdHint?: string) {
    const normalizedReceiptId = String(receiptIdHint || currentWalletReceiptId()).trim();
    const draftReceipt = tryParseWalletJsonDraft(walletReceiptDraft);

    if (draftReceipt) {
      const draftReceiptId = String(draftReceipt.receipt_id || "").trim();
      if (!normalizedReceiptId || !draftReceiptId || draftReceiptId === normalizedReceiptId) {
        const workflowName = currentWalletWorkflowName(draftReceipt);
        if (!workflowName) {
          throw new Error(tWork("security_invalid_workflow_name"));
        }
        const serviceId = currentWalletServiceId(workflowName);
        setWalletReceiptContext(draftReceipt, workflowName, serviceId);
        return {
          receipt: draftReceipt,
          receiptId: draftReceiptId || normalizedReceiptId,
          workflowName,
          serviceId,
        };
      }
    }

    if (!normalizedReceiptId) {
      throw new Error(tWork("wallet_receipt_lookup_required"));
    }

    const payload = await walletGetJson(`/v1/payments/receipts/status?receipt_id=${encodeURIComponent(normalizedReceiptId)}`);
    const receipt = payload?.receipt;
    if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
      throw new Error(tWork("wallet_receipt_status_missing"));
    }

    const workflowName = currentWalletWorkflowName(receipt);
    if (!workflowName) {
      throw new Error(tWork("security_invalid_workflow_name"));
    }
    const serviceId = currentWalletServiceId(workflowName);
    setWalletReceiptContext(receipt, workflowName, serviceId);
    return {
      receipt,
      receiptId: normalizedReceiptId,
      workflowName,
      serviceId,
    };
  }

  async function fetchWalletQueueSnapshot(
    receiptIdHint?: string,
    statusHint?: string,
    options: { announce?: boolean } = {},
  ) {
    const receiptId = String(receiptIdHint || currentWalletReceiptId()).trim();
    const status = String(statusHint ?? walletQueueStatusFilter).trim();
    const params = new URLSearchParams();
    if (receiptId) {
      params.set("receipt_id", receiptId);
    }
    if (status) {
      params.set("status", status);
    }

    const path = params.toString()
      ? `/v1/payments/receipts/onchain-relay-queue?${params.toString()}`
      : "/v1/payments/receipts/onchain-relay-queue";
    const payload = await walletGetJson(path);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    setWalletQueueItems(items);
    if (receiptId) {
      setWalletQueueReceiptId(receiptId);
    }
    if (options.announce !== false) {
      setWalletActionNotice(tWork("wallet_relay_queue_loaded", { count: items.length }));
    }
    return items;
  }

  async function fetchWalletRelayRecord(
    kind: "latest" | "latest-failed",
    receiptIdHint?: string,
    options: { announce?: boolean } = {},
  ) {
    const receiptId = String(receiptIdHint || currentWalletReceiptId()).trim();
    if (!receiptId) {
      throw new Error(tWork("wallet_receipt_lookup_required"));
    }

    const payload = await walletGetJson(`/v1/payments/receipts/onchain-relays/${kind}?receipt_id=${encodeURIComponent(receiptId)}`);
    if (kind === "latest") {
      setWalletLatestRelayRecord(payload);
      if (options.announce !== false) {
        setWalletActionNotice(tWork("wallet_relay_latest_loaded"));
      }
    } else {
      setWalletLatestFailedRelayRecord(payload);
      if (options.announce !== false) {
        setWalletActionNotice(tWork("wallet_relay_latest_failed_loaded"));
      }
    }
    setWalletQueueReceiptId(receiptId);
    return payload;
  }

  async function fetchWalletReplayHelper(
    lookup: { receipt_id?: string; relay_id?: string; queue_id?: string },
    options: { announce?: boolean } = {},
  ) {
    const payload = await walletPostJson("/v1/payments/receipts/onchain-relay/replay-helper", lookup);
    const helper = payload?.helper || payload;
    if (helper?.payment_receipt) {
      setWalletReceiptContext(helper.payment_receipt, helper.workflow_name, currentWalletServiceId(helper.workflow_name));
    }
    if (Array.isArray(helper?.direct_relay_request?.raw_transactions) && helper.direct_relay_request.raw_transactions.length > 0) {
      setWalletRelayRawTransactionsDraft(prettyJson(helper.direct_relay_request.raw_transactions));
    }
    if (String(helper?.direct_relay_request?.rpc_url || "").trim()) {
      setWalletRelayRpcUrl(String(helper.direct_relay_request.rpc_url || "").trim());
    }
    if (helper?.queue_requeue_request?.max_attempts) {
      setWalletQueueMaxAttempts(String(helper.queue_requeue_request.max_attempts));
    }
    setWalletRelayResult(helper);
    if (helper?.receipt_id) {
      setWalletQueueReceiptId(String(helper.receipt_id));
    }
    if (options.announce !== false) {
      setWalletActionNotice(tWork("wallet_relay_helper_loaded"));
    }
    return helper;
  }

  async function buildWalletOnchainProof() {
    const { receipt, workflowName, receiptId } = await resolveWalletReceiptContext();
    const result = await walletPostJson("/v1/payments/receipts/onchain-proof", {
      payment_receipt: receipt,
      workflow_name: workflowName,
    });
    setWalletRelayResult(result);
    if (receiptId) {
      setWalletQueueReceiptId(receiptId);
    }
    setWalletActionNotice(tWork("wallet_relay_proof_built"));
    return result;
  }

  async function buildWalletOnchainRpcPlan() {
    const { receipt, workflowName, receiptId } = await resolveWalletReceiptContext();
    const result = await walletPostJson("/v1/payments/receipts/onchain-rpc-plan", {
      payment_receipt: receipt,
      workflow_name: workflowName,
    });
    setWalletRelayResult(result);
    if (receiptId) {
      setWalletQueueReceiptId(receiptId);
    }
    setWalletActionNotice(tWork("wallet_relay_rpc_plan_built"));
    return result;
  }

  async function handleWalletQueueRelay(options: { allowPrepare?: boolean } = {}) {
    const { receipt, workflowName, receiptId } = await resolveWalletReceiptContext();

    if (!walletRelayRawTransactionsDraft.trim()) {
      if (options.allowPrepare) {
        const proof = await walletPostJson("/v1/payments/receipts/onchain-proof", {
          payment_receipt: receipt,
          workflow_name: workflowName,
        });
        setWalletRelayResult(proof);
        setWalletActionNotice(tWork("wallet_relay_prepare_queue"));
        return null;
      }
      throw new Error(tWork("wallet_relay_raw_transactions_required"));
    }

    const rawTransactions = parseWalletJsonArrayDraft(
      walletRelayRawTransactionsDraft,
      tWork("wallet_relay_raw_transactions_invalid"),
    );
    const payload: Record<string, unknown> = {
      payment_receipt: receipt,
      workflow_name: workflowName,
      raw_transactions: rawTransactions,
      timeout_seconds: parsedWalletRelayTimeoutSeconds(),
      delay_seconds: parsedWalletQueueDelaySeconds(),
    };
    const maxAttempts = parsedWalletQueueMaxAttempts();
    if (walletRelayRpcUrl.trim()) {
      payload.rpc_url = walletRelayRpcUrl.trim();
    }
    if (maxAttempts !== undefined) {
      payload.max_attempts = maxAttempts;
    }

    const result = await walletPostJson("/v1/payments/receipts/onchain-relay-queue", payload);
    setWalletRelayResult(result);
    setWalletQueueReceiptId(receiptId);
    await Promise.allSettled([
      fetchPaymentAndServiceState(localNodeToken),
      fetchWalletQueueSnapshot(receiptId, walletQueueStatusFilter, { announce: false }),
    ]);
    setWalletActionNotice(tWork("wallet_relay_queued"));
    return result;
  }

  async function handleWalletQueueItemAction(action: string, item: any) {
    const queueId = String(item?.id || "").trim();
    const receiptId = String(item?.receipt_id || currentWalletReceiptId()).trim();
    if (!queueId) {
      throw new Error(tWork("wallet_relay_queue_item_missing"));
    }

    if (action === "replay-helper") {
      return await fetchWalletReplayHelper({ queue_id: queueId });
    }

    const payload: Record<string, unknown> = { queue_id: queueId };
    const delaySeconds = parsedWalletQueueDelaySeconds();
    const maxAttempts = parsedWalletQueueMaxAttempts();

    if (action === "resume") {
      payload.delay_seconds = delaySeconds;
    }
    if (action === "requeue") {
      payload.delay_seconds = delaySeconds;
      if (maxAttempts !== undefined) {
        payload.max_attempts = maxAttempts;
      }
      if (String(item?.workflow_name || "").trim()) {
        payload.workflow_name = String(item.workflow_name);
      }
      if (walletRelayRpcUrl.trim()) {
        payload.rpc_url = walletRelayRpcUrl.trim();
      }
      payload.timeout_seconds = parsedWalletRelayTimeoutSeconds();
    }
    if (action === "disable-auto-requeue" && walletQueueReason.trim()) {
      payload.reason = walletQueueReason.trim();
    }

    const path = action === "pause"
      ? "/v1/payments/receipts/onchain-relay-queue/pause"
      : action === "resume"
        ? "/v1/payments/receipts/onchain-relay-queue/resume"
        : action === "requeue"
          ? "/v1/payments/receipts/onchain-relay-queue/requeue"
          : action === "cancel"
            ? "/v1/payments/receipts/onchain-relay-queue/cancel"
            : action === "delete"
              ? "/v1/payments/receipts/onchain-relay-queue/delete"
              : action === "disable-auto-requeue"
                ? "/v1/payments/receipts/onchain-relay-queue/auto-requeue/disable"
                : "/v1/payments/receipts/onchain-relay-queue/auto-requeue/enable";

    const result = await walletPostJson(path, payload);
    setWalletRelayResult(result?.item || result);
    if (receiptId) {
      setWalletQueueReceiptId(receiptId);
    }
    await Promise.allSettled([
      fetchPaymentAndServiceState(localNodeToken),
      fetchWalletQueueSnapshot(receiptId, walletQueueStatusFilter, { announce: false }),
    ]);
    setWalletActionNotice(tWork("wallet_queue_item_updated"));
    return result;
  }

  async function handleWalletRecommendedAction(action: string) {
    setWalletActionBusyKey(`recommended:${action}`);
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      if (action === "issue-renter-token") {
        const { receipt, workflowName, serviceId, receiptId } = await resolveWalletReceiptContext();
        const maxUses = Number(walletTokenMaxUses.trim() || 0);
        const issued = await handleRenterTokenOperations("issue", {
          payment_receipt: receipt,
          workflow_name: workflowName,
          service_id: serviceId || undefined,
          max_uses: Number.isFinite(maxUses) && maxUses > 0 ? maxUses : undefined,
        });
        const token = issued?.token || issued?.renter_token || issued;
        setWalletQueueReceiptId(receiptId);
        setWalletTokenDraft(prettyJson(token));
        setWalletTokenResult(issued);
        setWalletActionNotice(tWork("wallet_token_issue_success"));
        await fetchPaymentAndServiceState(localNodeToken).catch(() => undefined);
        return;
      }

      if (action === "introspect-receipt") {
        const { receipt, workflowName, receiptId } = await resolveWalletReceiptContext();
        const result = await handleReceiptOperations("introspect", {
          payment_receipt: receipt,
          workflow_name: workflowName || undefined,
        });
        setWalletQueueReceiptId(receiptId);
        setWalletReceiptResult(result);
        setWalletActionNotice(tWork("wallet_receipt_introspect_success"));
        return;
      }

      if (action === "build-payment-proof") {
        await buildWalletOnchainProof();
        return;
      }

      if (action === "queue-payment-relay") {
        await handleWalletQueueRelay({ allowPrepare: true });
        return;
      }

      if (action === "inspect-relay-queue") {
        await fetchWalletQueueSnapshot();
        return;
      }

      if (action === "inspect-latest-relay") {
        await fetchWalletRelayRecord("latest");
        return;
      }

      if (action === "inspect-latest-failed-relay") {
        await fetchWalletRelayRecord("latest-failed");
        return;
      }

      if (action === "replay-helper") {
        await fetchWalletReplayHelper({ receipt_id: currentWalletReceiptId() });
        return;
      }

      if (action === "requeue-payment-relay") {
        const helper = await fetchWalletReplayHelper({ receipt_id: currentWalletReceiptId() }, { announce: false });
        const request = helper?.queue_requeue_request;
        if (!request?.queue_id) {
          throw new Error(tWork("wallet_relay_requeue_unavailable"));
        }
        const payload: Record<string, unknown> = {
          queue_id: request.queue_id,
          workflow_name: request.workflow_name,
          timeout_seconds: parsedWalletRelayTimeoutSeconds(),
          delay_seconds: parsedWalletQueueDelaySeconds(),
        };
        const maxAttempts = parsedWalletQueueMaxAttempts();
        if (maxAttempts !== undefined) {
          payload.max_attempts = maxAttempts;
        } else if (request.max_attempts) {
          payload.max_attempts = request.max_attempts;
        }
        if (walletRelayRpcUrl.trim()) {
          payload.rpc_url = walletRelayRpcUrl.trim();
        } else if (String(request.rpc_url || "").trim()) {
          payload.rpc_url = String(request.rpc_url || "").trim();
        }
        const result = await walletPostJson("/v1/payments/receipts/onchain-relay-queue/requeue", payload);
        setWalletRelayResult(result?.item || result);
        await Promise.allSettled([
          fetchPaymentAndServiceState(localNodeToken),
          fetchWalletQueueSnapshot(String(helper?.receipt_id || currentWalletReceiptId()), walletQueueStatusFilter, { announce: false }),
        ]);
        setWalletActionNotice(tWork("wallet_queue_item_updated"));
        return;
      }

      if (action === "build-onchain-rpc-plan") {
        await buildWalletOnchainRpcPlan();
        return;
      }

      if (action === "inspect-renter-token-summary") {
        const summary = await walletGetJson("/v1/payments/renter-tokens/summary");
        setRenterTokenSummary(summary);
        setWalletTokenResult(summary);
        const itemCount = Array.isArray(summary?.items)
          ? summary.items.length
          : Number(summary?.token_count || summary?.total_tokens || 0);
        setWalletActionNotice(tWork("wallet_renter_token_summary_loaded", { count: itemCount }));
        return;
      }

      setWalletActionNotice(action);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  async function handleWalletIssueReceipt() {
    if (!walletReceiptIssueChallengeId.trim() || !walletReceiptIssuePayer.trim() || !walletReceiptIssueTxHash.trim()) {
      setWalletActionError(tWork("workflow_receipt_fields_required"));
      return;
    }

    setWalletActionBusyKey("issue-receipt");
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      const issued = await handleReceiptOperations("issue", {
        challenge_id: walletReceiptIssueChallengeId.trim(),
        payer: walletReceiptIssuePayer.trim(),
        tx_hash: walletReceiptIssueTxHash.trim(),
      });
      const receipt = issued?.receipt || null;
      const workflowName = String(receipt?.workflow_name || walletReceiptWorkflowName || "").trim();
      if (receipt) {
        setWalletReceiptDraft(prettyJson(receipt));
        if (String(receipt?.receipt_id || "").trim()) {
          setWalletQueueReceiptId(String(receipt.receipt_id));
        }
      }
      if (workflowName) {
        setWalletReceiptWorkflowName(workflowName);
        setWalletTokenWorkflowName((prev) => prev || workflowName);
      }
      setWalletReceiptResult(issued);
      setWalletActionNotice(tWork("workflow_receipt_issue_success"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("workflow_receipt_issue_success") }]);
      await fetchPaymentAndServiceState(localNodeToken).catch(() => undefined);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  async function handleWalletIntrospectReceipt() {
    setWalletActionBusyKey("introspect-receipt");
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      const receipt = parseWalletJsonDraft(walletReceiptDraft, tWork("wallet_receipt_json_invalid"));
      const workflowName = String(walletReceiptWorkflowName || (receipt as any).workflow_name || "").trim();
      const result = await handleReceiptOperations("introspect", {
        payment_receipt: receipt,
        workflow_name: workflowName || undefined,
      });
      if (String((receipt as any)?.receipt_id || "").trim()) {
        setWalletQueueReceiptId(String((receipt as any).receipt_id));
      }
      if (workflowName) {
        setWalletReceiptWorkflowName(workflowName);
      }
      setWalletReceiptResult(result);
      setWalletActionNotice(tWork("wallet_receipt_introspect_success"));
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  async function handleWalletIssueRenterToken() {
    setWalletActionBusyKey("issue-token");
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      const receipt = parseWalletJsonDraft(walletReceiptDraft, tWork("wallet_receipt_json_invalid"));
      const workflowName = String(walletTokenWorkflowName || walletReceiptWorkflowName || (receipt as any).workflow_name || "").trim();
      if (!workflowName) {
        throw new Error(tWork("security_invalid_workflow_name"));
      }
      const inferredServiceId = String(
        walletTokenServiceId || localServices.find((service: any) => workflowCandidatesForService(service).includes(workflowName))?.service_id || "",
      ).trim();
      const maxUsesValue = Number(walletTokenMaxUses.trim() || 0);
      const issued = await handleRenterTokenOperations("issue", {
        payment_receipt: receipt,
        workflow_name: workflowName,
        service_id: inferredServiceId || undefined,
        max_uses: Number.isFinite(maxUsesValue) && maxUsesValue > 0 ? maxUsesValue : undefined,
      });
      if (String((receipt as any)?.receipt_id || "").trim()) {
        setWalletQueueReceiptId(String((receipt as any).receipt_id));
      }
      const token = issued?.token || issued?.renter_token || issued;
      setWalletTokenDraft(prettyJson(token));
      setWalletTokenWorkflowName(workflowName);
      if (inferredServiceId) {
        setWalletTokenServiceId(inferredServiceId);
      }
      setWalletTokenResult(issued);
      setWalletActionNotice(tWork("wallet_token_issue_success"));
      setHistory((prev) => [...prev, { type: 'system', content: tWork("wallet_token_issue_success") }]);
      await fetchPaymentAndServiceState(localNodeToken).catch(() => undefined);
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  async function handleWalletIntrospectRenterToken() {
    setWalletActionBusyKey("introspect-token");
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      const token = parseWalletJsonDraft(walletTokenDraft, tWork("wallet_token_json_invalid"));
      const workflowName = String(walletTokenWorkflowName || (token as any).workflow_name || "").trim();
      const serviceId = String(walletTokenServiceId || (token as any).service_id || "").trim();
      const result = await handleRenterTokenOperations("introspect", {
        renter_token: token,
        workflow_name: workflowName || undefined,
        service_id: serviceId || undefined,
        operation: "workflow-execute",
      });
      if (workflowName) {
        setWalletTokenWorkflowName(workflowName);
      }
      if (serviceId) {
        setWalletTokenServiceId(serviceId);
      }
      setWalletTokenResult(result);
      setWalletActionNotice(tWork("wallet_token_introspect_success"));
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  async function runWalletUiAction(actionKey: string, action: () => Promise<void>) {
    if (walletActionBusyKey !== "") {
      return;
    }

    setWalletActionBusyKey(actionKey);
    setWalletActionError("");
    setWalletActionNotice("");

    try {
      await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : tWork("local_action_failed");
      setWalletActionError(message);
      setHistory((prev) => [...prev, { type: 'system', content: message }]);
    } finally {
      setWalletActionBusyKey("");
    }
  }

  function triggerWalletUiAction(actionKey: string, action: () => Promise<void>) {
    void runWalletUiAction(actionKey, action);
  }

  function handleWalletRelayQueueRefreshClick() {
    triggerWalletUiAction("relay-queue-refresh", async () => {
      await fetchWalletQueueSnapshot();
    });
  }

  function handleWalletRelayLatestClick() {
    triggerWalletUiAction("relay-latest", async () => {
      await fetchWalletRelayRecord("latest");
    });
  }

  function handleWalletRelayLatestFailedClick() {
    triggerWalletUiAction("relay-latest-failed", async () => {
      await fetchWalletRelayRecord("latest-failed");
    });
  }

  function handleWalletReplayHelperClick() {
    triggerWalletUiAction("relay-helper", async () => {
      await fetchWalletReplayHelper({ receipt_id: currentWalletReceiptId() });
    });
  }

  function handleWalletBuildProofClick() {
    triggerWalletUiAction("relay-build-proof", async () => {
      await buildWalletOnchainProof();
    });
  }

  function handleWalletBuildRpcPlanClick() {
    triggerWalletUiAction("relay-build-rpc-plan", async () => {
      await buildWalletOnchainRpcPlan();
    });
  }

  function handleWalletRelayQueueSubmitClick() {
    triggerWalletUiAction("relay-queue-submit", async () => {
      await handleWalletQueueRelay();
    });
  }

  function handleWalletRelayQueueItemClick(action: string, item: any) {
    const itemId = String(item?.id || "").trim() || action;
    triggerWalletUiAction(`${action}:${itemId}`, async () => {
      await handleWalletQueueItemAction(action, item);
    });
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
      const aliasesServices: string[] = tCmd.raw("aliases_services");
      const aliasesPayments: string[] = tCmd.raw("aliases_payments");
      const aliasesWorkflow: string[] = tCmd.raw("aliases_workflow");

      if (aliasesClear.includes(lowerCmd)) {
        setHistory([]);
      } else if (aliasesHelp.includes(lowerCmd)) {
        setHistory(prev => [...prev, { type: 'system', content: tCmd("help") }]);
      } else if (aliasesWorkflow.includes(lowerCmd)) {
        openWorkflowModal();
        setHistory(prev => [...prev, { type: 'system', content: tWork("workflow_modal_opened") }]);
      } else if (aliasesPing.includes(lowerCmd)) {
        const ms = Math.floor(Math.random() * 30 + 5);
        setHistory(prev => [...prev, { type: 'system', content: tCmd("ping", { ms }) }]);
      } else if (aliasesWhoamI.includes(lowerCmd)) {
        setHistory(prev => [...prev, { type: 'system', content: tCmd("whoami") }]);
      } else if (aliasesQueue.includes(lowerCmd)) {
        const lines = mockQueue.length === 0 
           ? tWork("empty_queue") 
           : mockQueue.map(q => tCmd("queue_line", { id: q.id, age: q.age })).join('\n');
        setHistory(prev => [...prev, { type: 'system', content: lines }]);
      } else if (aliasesServices.includes(lowerCmd)) {
        if (!localServices.length && !localCapabilities.length) {
           setHistory(prev => [...prev, { type: 'system', content: tCmd("services_empty") }]);
        } else {
           const lines = [
             tCmd("services_capabilities_title"),
             ...localCapabilities.map((c: any) => tCmd("services_capability_line", {
               name: String(c.id || c.name || tWork("community_value_unknown")),
               summary: String(c.description || c.summary || ""),
             })),
             tCmd("services_services_title"),
             ...localServices.map((s: any) => tCmd("services_service_line", {
               id: String(s.service_id || tWork("community_value_unknown")),
               price: String(s.price_per_call || 0),
               asset: String(s.price_asset || "CREDIT"),
             }))
           ].join("\n");
           setHistory(prev => [...prev, { type: 'system', content: lines }]);
        }
      } else if (aliasesPayments.includes(lowerCmd)) {
        if (!paymentOpsSummary && !renterTokenSummary) {
           setHistory(prev => [...prev, { type: 'system', content: tCmd("payments_empty") }]);
        } else {
           const queues = paymentOpsSummary?.queue_summary || {};
           const lines = [
             tCmd("payments_queue_title"),
             tCmd("payments_running_relays_line", { count: queues.running || 0 }),
             tCmd("payments_requeue_dead_line", { requeue: queues.requeue || 0, dead: queues.dead_letter || 0 }),
             tCmd("payments_reconciliation_title"),
             tCmd("payments_status_line", { status: String(serviceUsageReconciliation?.reconciliation_status || "idle") }),
             tCmd("payments_advised_action_line", { action: String(serviceUsageReconciliation?.recommended_actions?.[0] || tWork("wallet_value_unknown")) }),
             tCmd("payments_tokens_title"),
             tCmd("payments_count_line", { count: renterTokenSummary?.total_tokens || 0 }),
             tCmd("payments_remaining_uses_line", { count: serviceUsageSummary?.total_remaining_uses || 0 })
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
    const nextPath = pathname.startsWith(`/${locale}`)
      ? pathname.replace(`/${locale}`, `/${newLocale}`)
      : `/${newLocale}`;
    router.replace(nextPath);
  };

  const currentLanguageLabel = locale === "en"
    ? tWork("lang_en")
    : locale === "ja"
      ? tWork("lang_ja")
      : tWork("lang_zh");
  const currentThemeLabel = theme === "dark"
    ? tWork("dark_mode")
    : tWork("light_mode");
  const nextLanguage = locale === "en" ? "zh" : locale === "zh" ? "ja" : "en";
  const sidebarCompact = isDesktopViewport && sidebarCollapsed;
  const sidebarDesktopWidth = sidebarCompact ? SIDEBAR_WIDTH_COLLAPSED : sidebarWidth;
  const sidebarStyle = { "--sidebar-width": `${sidebarDesktopWidth}px` } as CSSProperties;
  const workflowTargetOptions = Array.from(
    new Set(localServices.flatMap((service: any) => workflowCandidatesForService(service))),
  ).sort((left, right) => left.localeCompare(right));
  const normalizedLocalMultimodalKind = String(localMultimodalKind || "").trim();
  const normalizedLocalMultimodalKindLower = normalizedLocalMultimodalKind.toLowerCase();
  const isAutomaticLocalMultimodalKind = !normalizedLocalMultimodalKind || normalizedLocalMultimodalKindLower === DEFAULT_LOCAL_TASK_KIND;
  const inferredCustomWorkflowTarget = !isAutomaticLocalMultimodalKind && !workflowTargetOptions.includes(normalizedLocalMultimodalKind);
  const showCustomWorkflowTargetInput = preferCustomWorkflowTarget || inferredCustomWorkflowTarget;
  const composeTaskRoutingVisible = showComposeTaskRouting || showCustomWorkflowTargetInput;
  const workflowTargetSelectValue = showCustomWorkflowTargetInput
    ? WORKFLOW_TARGET_CUSTOM_VALUE
    : isAutomaticLocalMultimodalKind
      ? ""
      : normalizedLocalMultimodalKind;
  const composeTaskTargetSummary = showCustomWorkflowTargetInput
    ? normalizedLocalMultimodalKind || tWork("local_multimodal_kind_custom_option")
    : isAutomaticLocalMultimodalKind
      ? tWork("local_multimodal_kind_auto_label")
      : normalizedLocalMultimodalKind;
  const composeRoutingButtonLabel = composeTaskRoutingVisible
    ? tWork("local_multimodal_kind_hide_advanced")
    : isAutomaticLocalMultimodalKind
      ? tWork("local_multimodal_kind_show_advanced")
      : `[ ${composeTaskTargetSummary} ]`;
  const workflowSelectedService = localServices.find((service: any) => {
    const workflowName = String(localMultimodalKind || "").trim();
    return workflowCandidatesForService(service).includes(workflowName);
  });
  const normalizedWorkflowModalKind = String(workflowModalKind || "").trim();
  const normalizedWorkflowModalKindLower = normalizedWorkflowModalKind.toLowerCase();
  const isAutomaticWorkflowModalKind = !normalizedWorkflowModalKind || normalizedWorkflowModalKindLower === DEFAULT_LOCAL_TASK_KIND;
  const inferredWorkflowModalCustomTarget = !isAutomaticWorkflowModalKind && !workflowTargetOptions.includes(normalizedWorkflowModalKind);
  const showWorkflowModalCustomTargetInput = workflowModalPreferCustomTarget || inferredWorkflowModalCustomTarget;
  const workflowModalTargetSelectValue = showWorkflowModalCustomTargetInput
    ? WORKFLOW_TARGET_CUSTOM_VALUE
    : isAutomaticWorkflowModalKind
      ? ""
      : normalizedWorkflowModalKind;
  const workflowModalSelectedService = localServices.find((service: any) => {
    return workflowCandidatesForService(service).includes(normalizedWorkflowModalKind);
  });
  const workflowNeedsPaymentProof = Boolean(
    workflowPaymentState?.payment && !workflowPaymentState?.receipt && !workflowPaymentState?.renterToken,
  );
  const workflowSubmitDisabled = workflowModalBusyAction !== "" || workflowNeedsPaymentProof || (!workflowModalPrompt.trim() && workflowModalAttachments.length === 0);
  const workflowSubmitLabel = workflowPaymentState?.renterToken
    ? tWork("workflow_resume_token")
    : workflowPaymentState?.receipt
      ? tWork("workflow_resume_receipt")
      : tWork("workflow_submit");

  const cycleLanguage = () => {
    switchLanguage(nextLanguage);
  };

  const cycleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  const toggleSidebarCollapsed = () => {
    if (!isDesktopViewport) return;

    if (sidebarCollapsed) {
      setSidebarCollapsed(false);
      setSidebarWidth(clamp(sidebarWidthBeforeCollapseRef.current, SIDEBAR_WIDTH_MIN, SIDEBAR_WIDTH_MAX));
      return;
    }

    sidebarWidthBeforeCollapseRef.current = sidebarWidth;
    setSidebarCollapsed(true);
  };

  const resizeSidebarBy = (delta: number) => {
    if (!isDesktopViewport) return;

    const dynamicMaxWidth = Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, window.innerWidth - 420));
    const nextWidth = clamp(sidebarWidth + delta, SIDEBAR_WIDTH_MIN, dynamicMaxWidth);
    setSidebarCollapsed(false);
    setSidebarWidth(nextWidth);
  };

  const handleWorkflowTargetSelection = (value: string) => {
    if (value === WORKFLOW_TARGET_CUSTOM_VALUE) {
      setPreferCustomWorkflowTarget(true);
      setLocalMultimodalKind(customLocalMultimodalKind.trim());
      return;
    }

    setPreferCustomWorkflowTarget(false);
    if (!value) {
      setLocalMultimodalKind(DEFAULT_LOCAL_TASK_KIND);
      return;
    }

    setLocalMultimodalKind(value);
  };

  const handleCustomWorkflowTargetChange = (value: string) => {
    setPreferCustomWorkflowTarget(true);
    setCustomLocalMultimodalKind(value);
    setLocalMultimodalKind(value);
  };

  const handleWorkflowModalTargetSelection = (value: string) => {
    if (value === WORKFLOW_TARGET_CUSTOM_VALUE) {
      setWorkflowModalPreferCustomTarget(true);
      setWorkflowModalKind(workflowModalCustomKind.trim());
      return;
    }

    setWorkflowModalPreferCustomTarget(false);
    if (!value) {
      setWorkflowModalKind(DEFAULT_LOCAL_TASK_KIND);
      return;
    }

    setWorkflowModalKind(value);
  };

  const handleWorkflowModalCustomTargetChange = (value: string) => {
    setWorkflowModalPreferCustomTarget(true);
    setWorkflowModalCustomKind(value);
    setWorkflowModalKind(value);
  };

  const isCopilotManagedRegistration = (registration: LocalManagedRegistration): boolean => {
    const identity = aiSubsystemIdentity(
      registration.title,
      registration.family,
      registration.type,
      registration.publisher,
      registration.preferred_integration,
      ...(registration.integration_candidates || []),
      ...(registration.protocols || []),
      registration.registration_id,
    );
    return preservedAiIconKeyForIdentity(identity) === "copilot";
  };

  const pickAcpListedSessionId = (session: LocalAcpSession): string => {
    const listed = Array.isArray(session.listed_server_sessions) ? [...session.listed_server_sessions] : [];
    listed.sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")));
    return String(session.loaded_server_session_id || listed[0]?.sessionId || "").trim();
  };

  const selectAcpTargetForRegistration = (
    snapshot: LocalRuntimeSnapshot,
    registrationId: string,
  ): { registration: LocalManagedRegistration; session?: LocalAcpSession } | null => {
    const registration = snapshot.managedRegistrations.find((item) => {
      return item.registration_id === registrationId && String(item.status || "").trim().toLowerCase() !== "closed";
    });

    if (!registration) return null;

    return {
      registration,
      session: acpSessionForRegistration(registration.registration_id, snapshot.acpSessions),
    };
  };

  const selectAutoAcpTarget = (
    snapshot: LocalRuntimeSnapshot,
    allowedRegistrationIds?: string[],
  ): { registration: LocalManagedRegistration; session?: LocalAcpSession } | null => {
    const allowedIds = Array.isArray(allowedRegistrationIds) && allowedRegistrationIds.length > 0
      ? new Set(allowedRegistrationIds)
      : null;
    const candidates = snapshot.managedRegistrations
      .filter((registration) => {
        if (String(registration.status || "").trim().toLowerCase() === "closed") return false;
        if (allowedIds && !allowedIds.has(registration.registration_id)) return false;
        return true;
      })
      .map((registration) => ({
        registration,
        session: acpSessionForRegistration(registration.registration_id, snapshot.acpSessions),
      }));

    if (candidates.length === 0) return null;

    const openCopilotCandidates = candidates.filter(({ registration, session }) => {
      return isCopilotManagedRegistration(registration) && String(session?.status || "").trim().toLowerCase() === "open";
    });
    if (openCopilotCandidates.length === 1) return openCopilotCandidates[0];

    const copilotCandidates = candidates.filter(({ registration }) => isCopilotManagedRegistration(registration));
    if (copilotCandidates.length === 1) return copilotCandidates[0];

    const openSessionCandidates = candidates.filter(({ session }) => String(session?.status || "").trim().toLowerCase() === "open");
    if (openSessionCandidates.length === 1) return openSessionCandidates[0];

    const runningCandidates = candidates.filter(({ registration }) => String(registration.status || "").trim().toLowerCase() === "running");
    if (runningCandidates.length === 1) return runningCandidates[0];

    if (candidates.length === 1) return candidates[0];
    return null;
  };

  const waitForAcpPollDelay = (ms: number) => new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

  const pollAcpSessionAndSync = async (sessionId: string): Promise<{ snapshot: LocalRuntimeSnapshot; session: LocalAcpSession }> => {
    await postLocalAction("/v1/discovery/local-agents/acp-session/poll", { session_id: sessionId });
    const snapshot = await fetchLocalAgentRuntimeState(localNodeToken);
    const session = snapshot.acpSessions.find((item) => item.session_id === sessionId);
    if (!session) {
      throw new Error(tWork("local_acp_action_failed"));
    }
    return { snapshot, session };
  };

  const waitForAcpSessionCondition = async (
    sessionId: string,
    predicate: (session: LocalAcpSession, snapshot: LocalRuntimeSnapshot) => boolean,
    attempts: number,
  ): Promise<{ snapshot: LocalRuntimeSnapshot; session: LocalAcpSession }> => {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const current = await pollAcpSessionAndSync(sessionId);
      if (predicate(current.session, current.snapshot)) {
        return current;
      }
      if (attempt < attempts - 1) {
        await waitForAcpPollDelay(ACP_AUTO_POLL_INTERVAL_MS);
      }
    }

    throw new Error(tWork("local_acp_auto_timeout_generic"));
  };

  const pushTerminalSystemMessage = (
    content: string,
    options?: Pick<TerminalHistoryEntry, "agentGlyph" | "agentName">,
  ) => {
    setHistory((prev) => [...prev, { type: "system", content, ...options }]);
  };

  const autoRouteTaskThroughAcp = async (
    taskId: string,
    routing?: {
      preferredRegistrationId?: string;
      allowedRegistrationIds?: string[];
      memberLabels?: string[];
    },
  ) => {
    const initialSnapshot = await fetchLocalAgentRuntimeState(localNodeToken);
    const allowedRegistrationIds = Array.isArray(routing?.allowedRegistrationIds)
      ? routing.allowedRegistrationIds.filter((item): item is string => Boolean(String(item || "").trim()))
      : [];
    const target = routing?.preferredRegistrationId
      ? selectAcpTargetForRegistration(initialSnapshot, routing.preferredRegistrationId)
        || selectAutoAcpTarget(initialSnapshot, allowedRegistrationIds)
      : selectAutoAcpTarget(initialSnapshot, allowedRegistrationIds);

    if (!target) {
      const fallbackMessage = routing?.preferredRegistrationId && allowedRegistrationIds.length <= 1
        ? tWork("local_acp_auto_selected_target_missing", {
            name: aiSubsystemCardsById.get(routing.preferredRegistrationId)?.name || routing.preferredRegistrationId,
          })
        : (allowedRegistrationIds.length > 0
          ? initialSnapshot.managedRegistrations.filter((item) => allowedRegistrationIds.includes(item.registration_id)).length
          : initialSnapshot.managedRegistrations.length) > 0
          ? tWork("local_acp_auto_manual_needed")
          : tWork("local_acp_auto_target_missing");
      pushTerminalSystemMessage(fallbackMessage);
      return;
    }

    let snapshot = initialSnapshot;
    let registration = target.registration;
    let session = target.session;
    const registrationLabel = registration.title || registration.registration_id;
    const terminalAgentBadge = terminalAgentBadgeForCard(
      aiSubsystemCardsById.get(registration.registration_id),
      registrationLabel,
    );

    if (routing?.memberLabels?.length === 1) {
      pushTerminalSystemMessage(tWork("local_acp_room_solo", { name: registrationLabel }));
    } else if ((routing?.memberLabels?.length || 0) > 1) {
      pushTerminalSystemMessage(tWork("local_acp_room_ready", {
        count: routing?.memberLabels?.length || 0,
        name: registrationLabel,
      }));
    }

    pushTerminalSystemMessage(tWork("local_acp_auto_waiting", { name: registrationLabel }));

    try {
      if (String(registration.status || "").trim().toLowerCase() !== "running") {
        await postLocalAction("/v1/discovery/local-agents/start", {
          registration_id: registration.registration_id,
        });
        snapshot = await fetchLocalAgentRuntimeState(localNodeToken);
        registration = snapshot.managedRegistrations.find((item) => item.registration_id === registration.registration_id) || registration;
        session = acpSessionForRegistration(registration.registration_id, snapshot.acpSessions);
      }

      if (!session) {
        await postLocalAction("/v1/discovery/local-agents/acp-session/open", {
          registration_id: registration.registration_id,
        });
        snapshot = await fetchLocalAgentRuntimeState(localNodeToken);
        session = acpSessionForRegistration(registration.registration_id, snapshot.acpSessions);
        if (!session) {
          throw new Error(tWork("local_acp_action_failed"));
        }
      }

      let serverSessionId = inferAcpServerSessionId(session);

      if (!serverSessionId) {
        await postLocalAction("/v1/discovery/local-agents/acp-session/initialize", {
          session_id: session.session_id,
          dispatch: true,
        });
        const initialized = await waitForAcpSessionCondition(
          session.session_id,
          (currentSession) => Boolean(currentSession.initialize_response_frame || inferAcpServerSessionId(currentSession)),
          ACP_AUTO_SETUP_POLL_ATTEMPTS,
        );
        snapshot = initialized.snapshot;
        session = initialized.session;
        serverSessionId = inferAcpServerSessionId(session);
      }

      if (!serverSessionId) {
        await postLocalAction("/v1/discovery/local-agents/acp-session/list", {
          session_id: session.session_id,
          dispatch: true,
        });
        const listed = await waitForAcpSessionCondition(
          session.session_id,
          (currentSession) => Array.isArray(currentSession.listed_server_sessions),
          ACP_AUTO_SETUP_POLL_ATTEMPTS,
        );
        snapshot = listed.snapshot;
        session = listed.session;
        const listedServerSessionId = pickAcpListedSessionId(session);

        if (listedServerSessionId) {
          await postLocalAction("/v1/discovery/local-agents/acp-session/load", {
            session_id: session.session_id,
            server_session_id: listedServerSessionId,
            dispatch: true,
          });
          const loaded = await waitForAcpSessionCondition(
            session.session_id,
            (currentSession) => {
              const loadedId = String(currentSession.loaded_server_session_id || "").trim();
              const inferredId = inferAcpServerSessionId(currentSession);
              return loadedId === listedServerSessionId || inferredId === listedServerSessionId;
            },
            ACP_AUTO_SETUP_POLL_ATTEMPTS,
          );
          snapshot = loaded.snapshot;
          session = loaded.session;
          serverSessionId = inferAcpServerSessionId(session) || listedServerSessionId;
        }
      }

      if (!serverSessionId) {
        pushTerminalSystemMessage(tWork("local_acp_auto_manual_needed"));
        return;
      }

      if (!session) {
        pushTerminalSystemMessage(tWork("local_acp_auto_manual_needed"));
        return;
      }

      const resolvedSession = session;

      setLocalSessionTaskInputs((prev) => ({
        ...prev,
        [resolvedSession.session_id]: {
          taskId,
          serverSessionId,
        },
      }));

      await postLocalAction("/v1/discovery/local-agents/acp-session/task-request", {
        session_id: resolvedSession.session_id,
        task_id: taskId,
        server_session_id: serverSessionId,
        dispatch: true,
      });

      const responded = await waitForAcpSessionCondition(
        resolvedSession.session_id,
        (currentSession) => Boolean(currentSession.task_response_captured || currentSession.latest_task_response_frame || currentSession.task_response_frame),
        ACP_AUTO_RESPONSE_POLL_ATTEMPTS,
      );
      snapshot = responded.snapshot;
      session = responded.session;

      const responsePreview = acpFrameText(session.latest_task_response_frame || session.task_response_frame || session.latest_server_frame);

      await postLocalAction("/v1/discovery/local-agents/acp-session/apply-task-result", {
        session_id: resolvedSession.session_id,
        task_id: taskId,
      });

      snapshot = await fetchLocalAgentRuntimeState(localNodeToken);
      const resolvedTask = snapshot.tasks.find((item) => item.id === taskId);
      const resultText = taskResultPreview(resolvedTask) || responsePreview;

      if (resultText) {
        pushTerminalSystemMessage(resultText, terminalAgentBadge);
      } else {
        pushTerminalSystemMessage(tWork("local_acp_auto_timeout", { name: registrationLabel }), terminalAgentBadge);
      }
    } catch (error) {
      const details = error instanceof Error ? error.message : tWork("local_acp_auto_timeout_generic");
      pushTerminalSystemMessage(tWork("local_acp_auto_failed", { name: registrationLabel, details }), terminalAgentBadge);
    }
  };

  const openIntroExperience = () => {
    setShowTutorial(false);
    setTutorialStepIndex(0);
    setLandingMode("manual");
    setPendingTutorialAfterLanding(true);
    setShowLanding(true);
  };

  const closeTutorial = () => {
    setShowTutorial(false);
    setTutorialStepIndex(0);
  };

  const handleLandingContinue = () => {
    if (landingMode === "first-run") {
      window.localStorage.setItem(INTRO_STORAGE_KEY, "1");
    }

    const shouldStartTutorial = pendingTutorialAfterLanding;
    setShowLanding(false);
    setLandingMode(null);
    setPendingTutorialAfterLanding(false);

    if (shouldStartTutorial) {
      setShowTutorial(true);
      setTutorialStepIndex(0);
    }
  };

  useEffect(() => {
    if (!USE_LEGACY_LANDING_ROUTE || !showLanding) return;

    const handleLegacyLandingMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.data?.type !== "agentcoin-legacy-landing-complete") return;
      handleLandingContinue();
    };

    window.addEventListener("message", handleLegacyLandingMessage);
    return () => {
      window.removeEventListener("message", handleLegacyLandingMessage);
    };
  }, [showLanding, landingMode, pendingTutorialAfterLanding]);

  const runningRegistrations = localManagedRegistrations.filter((item) => item.status === "running").length;
  const transportReadySessions = localAcpSessions.filter((item) => item.status === "open").length;
  const totalCapturedFrames = localAcpSessions.reduce((sum, item) => sum + Number(item.server_frames_seen || 0), 0);
  const aiSubsystemStatusMeta: Record<
    AiSubsystemCardStatus,
    { label: string; code: string; toneClass: string; dotClass: string }
  > = {
    open: {
      label: tWork("ai_subsystem_status_open"),
      code: "ACP",
      toneClass: "text-[#5FEADB]",
      dotClass: "bg-[#5FEADB] shadow-[0_0_10px_rgba(95,234,219,0.55)]",
    },
    running: {
      label: tWork("ai_subsystem_status_running"),
      code: "RUN",
      toneClass: "text-[#F4C76B]",
      dotClass: "bg-[#F4C76B] shadow-[0_0_10px_rgba(244,199,107,0.45)]",
    },
    registered: {
      label: tWork("ai_subsystem_status_registered"),
      code: "REG",
      toneClass: "text-[#7DD3FC]",
      dotClass: "bg-[#7DD3FC] shadow-[0_0_10px_rgba(125,211,252,0.45)]",
    },
    attachable: {
      label: tWork("ai_subsystem_status_attachable"),
      code: "ADD",
      toneClass: "text-[#86EFAC]",
      dotClass: "bg-[#86EFAC] shadow-[0_0_10px_rgba(134,239,172,0.45)]",
    },
    inspect: {
      label: tWork("ai_subsystem_status_inspect"),
      code: "CHK",
      toneClass: "text-[#FCA5A5]",
      dotClass: "bg-[#FCA5A5] shadow-[0_0_10px_rgba(252,165,165,0.35)]",
    },
  };
  const localDiscoveryById = new Map(localDiscoveryItems.map((item) => [item.id, item]));
  const aiSubsystemCards: AiSubsystemCard[] = [];

  for (const registration of localManagedRegistrations) {
    const discoveredId = String(registration.discovered_id || "").trim();
    const discovery = discoveredId ? localDiscoveryById.get(discoveredId) : undefined;
    const session = acpSessionForRegistration(registration.registration_id, localAcpSessions);
    const normalizedStatus = String(registration.status || "").trim().toLowerCase();
    const status: AiSubsystemCardStatus = session
      ? "open"
      : normalizedStatus === "running"
        ? "running"
        : "registered";
    const summary = aiSubsystemSummaryForManaged(registration, discovery, session);
    const identity = aiSubsystemIdentity(
      registration.title,
      discovery?.title,
      registration.family,
      registration.publisher,
      registration.registration_id,
      registration.type,
      summary,
    );

    const iconKey = preservedAiIconKeyForIdentity(identity);

    aiSubsystemCards.push({
      id: registration.registration_id,
      name: registration.title || discovery?.title || registration.registration_id,
      summary: summary || registration.transport || discovery?.type || registration.registration_id,
      glyph: aiSubsystemGlyph(
        discovery ? discoveryBadge(discovery) : managedRegistrationBadge(registration),
        aiSubsystemStatusMeta[status].code,
      ),
      status,
      iconKey,
      icon: preservedAiIcon(iconKey),
    });
  }

  const aiSubsystemCardsById = new Map(aiSubsystemCards.map((card) => [card.id, card]));

  const renderAiCardVisual = (agent: Pick<AiSubsystemCard, "icon" | "glyph" | "status">) => {
    const statusMeta = aiSubsystemStatusMeta[agent.status];

    if (agent.icon) {
      return agent.icon;
    }

    return (
      <pre className={`m-0 shrink-0 select-none rounded-sm border border-current/20 bg-black/50 px-1.5 py-1 text-[8px] font-bold leading-[0.92] tracking-[0.18em] opacity-85 transition-all group-hover:opacity-100 ${statusMeta.toneClass}`}>
        {agent.glyph}
      </pre>
    );
  };

  const renderAiSubsystemCards = (options?: {
    selectable?: boolean;
    selectedIds?: string[];
    onToggleSelection?: (agentId: string) => void;
  }) => {
    const selectable = options?.selectable || false;
    const selectedIds = new Set(options?.selectedIds || []);

    if (aiSubsystemCards.length === 0) {
      return (
        <div className="rounded-sm border border-foreground/20 bg-foreground/5 px-3 py-3 text-[10px] uppercase tracking-[0.18em] opacity-80">
          <div>{tWork("ai_subsystem_empty")}</div>
          <div className="mt-1 normal-case tracking-normal opacity-60">{tWork("ai_subsystem_empty_hint")}</div>
        </div>
      );
    }

    return (
      <div className="space-y-2.5">
        {aiSubsystemCards.map((agent) => {
          const statusMeta = aiSubsystemStatusMeta[agent.status];
          const isSelected = selectedIds.has(agent.id);
          const cardClassName = `flex w-full items-center justify-between gap-3 rounded-sm border px-3 py-2.5 text-left transition-all ${selectable ? "cursor-pointer focus:outline-none focus-visible:border-foreground focus-visible:bg-foreground/16" : ""} ${isSelected ? "border-foreground bg-foreground/[0.18] shadow-[0_0_18px_rgba(255,255,255,0.08)]" : "border-foreground/20 bg-foreground/10 hover:border-foreground/35 hover:bg-foreground/15"}`;
          const content = (
            <>
              <div className="flex min-w-0 items-center gap-3">
                {renderAiCardVisual(agent)}
                <div className="min-w-0">
                  <div className="truncate whitespace-nowrap text-sm font-bold">{agent.name}</div>
                  <div className="truncate whitespace-nowrap text-[10px] opacity-65">{agent.summary}</div>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 pl-2">
                {selectable && (
                  <span className={`rounded-sm border px-1.5 py-0.5 text-[9px] normal-case tracking-[0.12em] ${isSelected ? "border-foreground bg-foreground text-background font-bold" : "border-foreground/25 opacity-70"}`}>
                    {isSelected ? tWork("ai_subsystem_selected_action") : tWork("ai_subsystem_select_action")}
                  </span>
                )}
                <span className={`h-2.5 w-2.5 rounded-full ${statusMeta.dotClass}`} />
                <span className={`whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.16em] ${statusMeta.toneClass}`}>
                  {statusMeta.label}
                </span>
              </div>
            </>
          );

          return (
            <div key={agent.id} className="group text-foreground animate-fade-in">
              {selectable ? (
                <button
                  type="button"
                  className={cardClassName}
                  onClick={() => options?.onToggleSelection?.(agent.id)}
                  aria-pressed={isSelected}
                >
                  {content}
                </button>
              ) : (
                <div className={cardClassName}>
                  {content}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  useEffect(() => {
    if (USE_LEGACY_LANDING_ROUTE || !showLanding) return;

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
    if (USE_LEGACY_LANDING_ROUTE || !showLanding) return;
    const container = landingScrollRef.current;
    if (!container) return;

    const frame = requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });

    return () => cancelAnimationFrame(frame);
  }, [typedVision, showLanding, landingStep]);

  if (!mounted || !introBootstrapComplete) return null;

  const tutorialWorkspaceLabel = activeWorkspaceWindow === "compose"
    ? tWork("window_compose")
    : activeWorkspaceWindow === "node"
      ? tWork("window_node")
      : activeWorkspaceWindow === "swarm"
        ? tWork("window_swarm")
        : activeWorkspaceWindow === "wallet"
          ? tWork("window_wallet")
          : tWork("window_community");

  const tutorialSteps: Array<{ id: TutorialStepId; title: string; body: string }> = [
    {
      id: "rail",
      title: tWork("tour_step_windows_title"),
      body: tWork("tour_step_windows_body"),
    },
    {
      id: "status",
      title: tWork("tour_step_status_title"),
      body: tWork("tour_step_status_body"),
    },
    {
      id: "alerts",
      title: tWork("tour_step_alerts_title"),
      body: tWork("tour_step_alerts_body"),
    },
    {
      id: "workspace",
      title: tWork("tour_step_workspace_title"),
      body: tWork("tour_step_workspace_body", { window: tutorialWorkspaceLabel }),
    },
  ];
  const activeTutorialStep = showTutorial ? tutorialSteps[tutorialStepIndex] || null : null;
  const activeTutorialRect = activeTutorialStep && typeof document !== "undefined"
    ? document.querySelector<HTMLElement>(`[data-tour-target="${activeTutorialStep.id}"]`)?.getBoundingClientRect() || null
    : null;
  const viewportWidth = typeof window !== "undefined" ? window.innerWidth : 1440;
  const viewportHeight = typeof window !== "undefined" ? window.innerHeight : 900;
  const tutorialCardWidth = Math.min(360, Math.max(280, viewportWidth - 32));
  const tutorialFocusStyle = activeTutorialRect
    ? {
        top: `${clamp(activeTutorialRect.top - 10, 12, Math.max(12, viewportHeight - 72))}px`,
        left: `${clamp(activeTutorialRect.left - 10, 12, Math.max(12, viewportWidth - 72))}px`,
        width: `${Math.max(120, Math.min(activeTutorialRect.width + 20, viewportWidth - 24))}px`,
        height: `${Math.max(60, Math.min(activeTutorialRect.height + 20, viewportHeight - 24))}px`,
      }
    : null;
  const preferredTutorialCardTop = activeTutorialRect ? activeTutorialRect.bottom + 18 : 24;
  const fallbackTutorialCardTop = activeTutorialRect ? activeTutorialRect.top - 230 : 24;
  const tutorialCardTop = clamp(
    preferredTutorialCardTop + 220 > viewportHeight ? fallbackTutorialCardTop : preferredTutorialCardTop,
    16,
    Math.max(16, viewportHeight - 240),
  );
  const tutorialCardLeft = clamp(
    activeTutorialRect ? activeTutorialRect.left : 24,
    16,
    Math.max(16, viewportWidth - tutorialCardWidth - 16),
  );

  const asciiBackdropLayer = (
    <div aria-hidden className="pointer-events-none fixed inset-[-4%] z-0 overflow-hidden bg-black">
      <canvas ref={asciiCanvasRef} className="absolute inset-0 h-full w-full opacity-100" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_52%,rgba(255,255,255,0.08),transparent_26%),radial-gradient(circle_at_50%_90%,rgba(255,255,255,0.04),transparent_38%)] opacity-100" />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(0,0,0,0.16),rgba(0,0,0,0.04)_28%,rgba(0,0,0,0.35)_72%,rgba(0,0,0,0.78))]" />
    </div>
  );

  if (showLanding) {
    if (USE_LEGACY_LANDING_ROUTE) {
      return (
        <div className="min-h-screen bg-black">
          <iframe
            title="AgentCoin Legacy Intro"
            src={`/${locale}/legacy-intro`}
            className="h-[100dvh] w-full border-0"
          />
        </div>
      );
    }

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
                    {pendingTutorialAfterLanding
                      ? tWork("intro_begin_tour")
                      : tWork("btn_enter_workspace", { defaultValue: "[ Initialize Workspace ]" })}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    }

  const walletQueueSummary = paymentOpsSummary?.queue_summary && typeof paymentOpsSummary.queue_summary === "object"
    ? paymentOpsSummary.queue_summary as Record<string, unknown>
    : {};
  const walletQueueEntries = Object.entries(walletQueueSummary).filter(([, value]) => (
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  ));
  const walletUsageItems: any[] = Array.isArray(serviceUsageSummary?.items)
    ? serviceUsageSummary.items
    : Array.isArray(serviceUsageSummary?.services)
      ? serviceUsageSummary.services
      : [];
  const walletTokenItems: any[] = Array.isArray(renterTokenSummary?.items)
    ? renterTokenSummary.items
    : Array.isArray(renterTokenSummary?.tokens)
      ? renterTokenSummary.tokens
      : [];
  const walletRecommendedActions: string[] = Array.isArray(serviceUsageReconciliation?.recommended_actions)
    ? serviceUsageReconciliation.recommended_actions
        .map((item: unknown) => String(item || "").trim())
        .filter(Boolean)
    : [];
  const walletLedgerReady = Boolean(paymentOpsSummary || serviceUsageSummary || serviceUsageReconciliation || renterTokenSummary);
  const walletRunningRelays = Number(paymentOpsSummary?.queue_summary?.running || 0);
  const walletRequeueCount = Number(paymentOpsSummary?.queue_summary?.requeue || 0);
  const walletDeadLetters = Number(paymentOpsSummary?.queue_summary?.dead_letter || 0);
  const walletTokenTotal = Number(renterTokenSummary?.total_tokens || serviceUsageSummary?.active_tokens || walletTokenItems.length || 0);
  const walletRemainingUses = Number(serviceUsageSummary?.total_remaining_uses || 0);
  const walletLatestRelayDisplay = walletLatestRelayRecord || paymentOpsSummary?.latest_relay || null;
  const walletLatestFailedRelayDisplay = walletLatestFailedRelayRecord || paymentOpsSummary?.latest_failed_relay || null;
  const walletReconciliationStatus = String(serviceUsageReconciliation?.reconciliation_status || tWork("wallet_value_unknown"));
  const walletLastUpdated = String(
    serviceUsageReconciliation?.updated_at ||
    serviceUsageReconciliation?.generated_at ||
    serviceUsageSummary?.updated_at ||
    paymentOpsSummary?.generated_at ||
    renterTokenSummary?.generated_at ||
    ""
  ).trim();
  const walletAttentionMessage = localLedgerError || (
    walletDeadLetters > 0
      ? tWork("wallet_attention_dead_letter", { count: walletDeadLetters })
      : walletRecommendedActions.length > 0
        ? tWork("wallet_attention_actions", { count: walletRecommendedActions.length })
        : ""
  );
  const swarmPeerIds = Array.from(new Set([
    ...remotePeers.map((peer) => peer.peer_id),
    ...remotePeerCards.map((card) => String(card.peer_id || "")).filter(Boolean),
    ...remotePeerHealth.map((health) => String(health.peer_id || "")).filter(Boolean),
  ]));
  const swarmPeers = swarmPeerIds.map((peerId) => {
    const peer = remotePeers.find((item) => item.peer_id === peerId);
    const card = remotePeerCards.find((item) => item.peer_id === peerId);
    const health = remotePeerHealth.find((item) => item.peer_id === peerId);
    return { peerId, peer, card, health };
  });
  const swarmGraphReady = swarmPeers.length > 0;
  const swarmBlacklistedCount = swarmPeers.filter((item) => item.health?.blacklisted_until).length;
  const swarmCooldownCount = swarmPeers.filter((item) => !item.health?.blacklisted_until && item.health?.cooldown_until).length;
  const swarmTrustReviewCount = swarmPeers.filter((item) => item.card?.identity_trust?.requires_review).length;
  const swarmAttentionMessage = remotePeersError || (
    swarmBlacklistedCount > 0
      ? tWork("swarm_attention_blacklisted", { count: swarmBlacklistedCount })
      : swarmTrustReviewCount > 0
        ? tWork("swarm_attention_review", { count: swarmTrustReviewCount })
        : ""
  );
  const communityServices = Array.isArray(localServices) ? localServices : [];
  const communityCapabilities = Array.isArray(localCapabilities) ? localCapabilities : [];
  const communityDirectory = swarmPeers.filter((item) => item.card || item.peer);
  const communityCatalogCount = communityServices.length + communityCapabilities.length;
  const communityAlignedCount = communityDirectory.filter((item) => item.card?.identity_trust?.aligned).length;
  const communityReviewCount = communityDirectory.filter((item) => item.card?.identity_trust?.requires_review).length;
  const communityProtocolCount = Array.from(new Set(communityDirectory.flatMap((item) => [
    ...(Array.isArray(item.card?.card?.protocols) ? item.card?.card?.protocols || [] : []),
    ...(Array.isArray(item.peer?.tags) ? item.peer?.tags || [] : []),
  ].map((value) => String(value || "").trim()).filter(Boolean)))).length;
  const communityWindowReady = communityCatalogCount > 0 || communityDirectory.length > 0;

  const alertEntries: Array<{
    id: string;
    windowId: WorkspaceWindowId;
    severity: "critical" | "watch";
    title: string;
    message: string;
  }> = [
    ...(localMultimodalError ? [{
      id: "compose-dispatch",
      windowId: "compose" as const,
      severity: "critical" as const,
      title: tWork("local_multimodal_label"),
      message: localMultimodalError,
    }] : []),
    ...(localNodeError ? [{
      id: "node-connectivity",
      windowId: "node" as const,
      severity: "critical" as const,
      title: tWork("local_node_label"),
      message: localNodeError,
    }] : []),
    ...(localRuntimeError ? [{
      id: "node-runtime",
      windowId: "node" as const,
      severity: "critical" as const,
      title: tWork("local_managed_label"),
      message: localRuntimeError,
    }] : []),
    ...(remotePeersError ? [{
      id: "swarm-remote-state",
      windowId: "swarm" as const,
      severity: "critical" as const,
      title: tWork("remote_peers_label"),
      message: remotePeersError,
    }] : []),
    ...(!remotePeersError && swarmBlacklistedCount > 0 ? [{
      id: "swarm-blacklisted",
      windowId: "swarm" as const,
      severity: "watch" as const,
      title: tWork("window_swarm"),
      message: tWork("swarm_attention_blacklisted", { count: swarmBlacklistedCount }),
    }] : []),
    ...(!remotePeersError && swarmTrustReviewCount > 0 ? [{
      id: "swarm-review",
      windowId: "swarm" as const,
      severity: "watch" as const,
      title: tWork("window_swarm"),
      message: tWork("swarm_attention_review", { count: swarmTrustReviewCount }),
    }] : []),
    ...(localLedgerError ? [{
      id: "wallet-ledger",
      windowId: "wallet" as const,
      severity: "critical" as const,
      title: tWork("wallet_ledger_title"),
      message: localLedgerError,
    }] : []),
    ...(!localLedgerError && walletDeadLetters > 0 ? [{
      id: "wallet-dead-letter",
      windowId: "wallet" as const,
      severity: "watch" as const,
      title: tWork("window_wallet"),
      message: tWork("wallet_attention_dead_letter", { count: walletDeadLetters }),
    }] : []),
    ...(!localLedgerError && walletRecommendedActions.length > 0 ? [{
      id: "wallet-actions",
      windowId: "wallet" as const,
      severity: "watch" as const,
      title: tWork("window_wallet"),
      message: tWork("wallet_attention_actions", { count: walletRecommendedActions.length }),
    }] : []),
  ];
  const alertCounts = {
    critical: alertEntries.filter((item) => item.severity === "critical").length,
    watch: alertEntries.filter((item) => item.severity === "watch").length,
  };
  const criticalAlertEntries = alertEntries.filter((item) => item.severity === "critical");
  const watchAlertEntries = alertEntries.filter((item) => item.severity === "watch");
  const shellAlertSummary = alertEntries.length > 0
    ? tWork("alert_summary_counts", { total: alertEntries.length, critical: alertCounts.critical, watch: alertCounts.watch })
    : tWork("alert_summary_clear");
  const getAlertSeverityLabel = (severity: "critical" | "watch") => (
    severity === "critical" ? tWork("alert_severity_critical") : tWork("alert_severity_watch")
  );
  const getWindowAlerts = (windowId: WorkspaceWindowId) => alertEntries.filter((item) => item.windowId === windowId);
  const getWindowAlertCount = (windowId: WorkspaceWindowId) => getWindowAlerts(windowId).length;

  const workspaceWindows: Array<{
    id: WorkspaceWindowId;
    label: string;
    planned: boolean;
    alert: boolean;
  }> = [
              { id: "compose", label: tWork("window_compose"), planned: false, alert: getWindowAlertCount("compose") > 0 },
              { id: "node", label: tWork("window_node"), planned: false, alert: getWindowAlertCount("node") > 0 },
              { id: "swarm", label: tWork("window_swarm"), planned: false, alert: getWindowAlertCount("swarm") > 0 },
              { id: "wallet", label: tWork("window_wallet"), planned: false, alert: getWindowAlertCount("wallet") > 0 },
              { id: "community", label: tWork("window_community"), planned: false, alert: false },
  ];
  const alertSummaryGroups = [
    {
      id: "total" as const,
      label: tWork("alert_summary_total_chip", { count: alertEntries.length }),
      alerts: alertEntries,
    },
    {
      id: "critical" as const,
      label: tWork("alert_summary_critical_chip", { count: alertCounts.critical }),
      alerts: criticalAlertEntries,
    },
    {
      id: "watch" as const,
      label: tWork("alert_summary_watch_chip", { count: alertCounts.watch }),
      alerts: watchAlertEntries,
    },
  ];
  const hoveredAlertGroup = hoveredAlertGroupId
    ? alertSummaryGroups.find((group) => group.id === hoveredAlertGroupId) || null
    : null;
  const alertPopoverToneClass = theme === "dark"
    ? "border-white bg-white text-black shadow-[0_0_26px_rgba(255,255,255,0.34)]"
    : "border-black bg-black text-white shadow-[0_0_26px_rgba(0,0,0,0.34)]";
  const alertPopoverItemToneClass = theme === "dark"
    ? "border-[#d6d6d6] bg-[#f3f3f3] text-black"
    : "border-[#555] bg-[#111] text-white";

            const pendingCriticalWindowLabel = pendingCriticalAction
              ? workspaceWindows.find((item) => item.id === pendingCriticalAction.windowId)?.label || (pendingCriticalAction.windowId === "compose" ? tWork("window_compose") : tWork("window_node"))
              : "";
            const criticalActionGuardTitle = pendingCriticalAction?.type === "stop-registration"
              ? tWork("critical_action_guard_stop_title")
              : pendingCriticalAction?.type === "close-acp-session"
                ? tWork("critical_action_guard_close_title")
                : pendingCriticalAction?.type === "clear-compose-attachments"
                  ? tWork("critical_action_guard_clear_attachments_title")
                  : pendingCriticalAction?.type === "disconnect-local-node"
                    ? tWork("critical_action_guard_disconnect_title")
                : "";
            const criticalActionGuardBody = pendingCriticalAction?.type === "stop-registration"
              ? tWork("critical_action_guard_stop_body", { name: pendingCriticalAction.registrationLabel })
              : pendingCriticalAction?.type === "close-acp-session"
                ? tWork("critical_action_guard_close_body", {
                    name: pendingCriticalAction.registrationLabel,
                    sessionId: pendingCriticalAction.sessionId,
                  })
                : pendingCriticalAction?.type === "clear-compose-attachments"
                  ? tWork("critical_action_guard_clear_attachments_body", { count: pendingCriticalAction.attachmentCount })
                  : pendingCriticalAction?.type === "disconnect-local-node"
                    ? tWork("critical_action_guard_disconnect_body", {
                        registrations: pendingCriticalAction.registrationCount,
                        sessions: pendingCriticalAction.sessionCount,
                        catalog: pendingCriticalAction.catalogCount,
                      })
                : "";
            const criticalActionGuardConfirmLabel = pendingCriticalAction?.type === "stop-registration"
              ? tWork("local_stop")
              : pendingCriticalAction?.type === "close-acp-session"
                ? tWork("local_acp_close")
                : pendingCriticalAction?.type === "clear-compose-attachments"
                  ? tWork("local_multimodal_clear_files")
                  : pendingCriticalAction?.type === "disconnect-local-node"
                    ? tWork("disconnect")
                : tWork("critical_action_guard_cancel");

            const activeWindowMeta = workspaceWindows.find((item) => item.id === activeWorkspaceWindow) || workspaceWindows[0];
            const shellNodeState = localNodeBusy
              ? tWork("local_node_status_checking")
              : localNodeOnline
                ? tWork("local_node_status_online")
                : tWork("local_node_status_offline");

            const getWalletQueueLabel = (key: string) => {
              if (key === "running") return tWork("wallet_queue_running_label");
              if (key === "requeue") return tWork("wallet_queue_requeue_label");
              if (key === "dead_letter") return tWork("wallet_queue_dead_letter_label");
              return key.replace(/_/g, " ");
            };

            const getWalletRecommendedActionLabel = (action: string) => {
              if (action === "issue-renter-token") return tWork("wallet_recommended_action_issue_renter_token");
              if (action === "introspect-receipt") return tWork("wallet_recommended_action_introspect_receipt");
              if (action === "build-payment-proof") return tWork("wallet_recommended_action_build_payment_proof");
              if (action === "queue-payment-relay") return tWork("wallet_recommended_action_queue_payment_relay");
              if (action === "inspect-relay-queue") return tWork("wallet_recommended_action_inspect_relay_queue");
              if (action === "inspect-latest-relay") return tWork("wallet_recommended_action_inspect_latest_relay");
              if (action === "inspect-latest-failed-relay") return tWork("wallet_recommended_action_inspect_latest_failed_relay");
              if (action === "replay-helper") return tWork("wallet_recommended_action_replay_helper");
              if (action === "requeue-payment-relay") return tWork("wallet_recommended_action_requeue_payment_relay");
              if (action === "build-onchain-rpc-plan") return tWork("wallet_recommended_action_build_onchain_rpc_plan");
              if (action === "inspect-renter-token-summary") return tWork("wallet_recommended_action_inspect_renter_token_summary");
              return action.replace(/-/g, " ");
            };

            const getPlannedWindowCopy = (windowId: WorkspaceWindowId) => {
              if (windowId === "swarm") {
                return {
                  title: tWork("planned_window_swarm_title"),
                  body: tWork("planned_window_swarm_body"),
                  status: tWork("planned_window_swarm_status"),
                  next: tWork("planned_window_swarm_next"),
                };
              }

              if (windowId === "wallet") {
                return {
                  title: tWork("planned_window_wallet_title"),
                  body: tWork("planned_window_wallet_body"),
                  status: tWork("planned_window_wallet_status"),
                  next: tWork("planned_window_wallet_next"),
                };
              }

              if (windowId === "community") {
                return {
                  title: tWork("planned_window_community_title"),
                  body: tWork("planned_window_community_body"),
                  status: tWork("planned_window_community_status"),
                  next: tWork("planned_window_community_next"),
                };
              }

              return {
                title: tWork("planned_window_title"),
                body: tWork("planned_window_body"),
                status: tWork("planned_window_body"),
                next: tWork("planned_window_phase_note"),
              };
            };

            const activePlannedWindow = getPlannedWindowCopy(activeWorkspaceWindow);

            const composeWindowContent = (
              <div className="grid h-full min-h-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
                <div className="flex min-h-0 flex-col border-2 border-foreground bg-foreground/[0.03] relative p-4 pt-10 shadow-[0_0_28px_rgba(255,255,255,0.05)]">
                  <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold z-10">
                    {tWork("terminal_label")}
                  </div>

                  <div className="overflow-y-auto custom-scrollbar flex-grow pb-3 pr-1 space-y-1">
                    <pre className="text-muted-foreground mb-6 whitespace-pre-wrap leading-tight text-[10px] sm:text-xs md:text-sm">
                      {ASCII_ART}
                    </pre>

                    {history.map((msg, i) => (
                      <div key={i} className={`${msg.type === 'user' ? 'text-foreground' : msg.agentGlyph ? 'text-foreground' : 'text-muted-foreground'} whitespace-pre-wrap text-sm sm:text-base`}>
                        {msg.type === 'system' && msg.agentGlyph ? (
                          <div className="grid grid-cols-[auto_1fr] items-start gap-3" title={msg.agentName || undefined}>
                            <pre className="m-0 shrink-0 select-none rounded-sm border border-foreground/15 bg-black/35 px-1.5 py-1 text-[8px] font-bold leading-[0.92] tracking-[0.18em] text-foreground/90">
                              {msg.agentGlyph}
                            </pre>
                            <div className="min-w-0 whitespace-pre-wrap break-words pt-0.5">
                              <span className="mr-2 text-muted-foreground">:</span>
                              <span>{msg.content}</span>
                            </div>
                          </div>
                        ) : (
                          msg.type === 'system' ? `> ${msg.content}` : msg.content
                        )}
                      </div>
                    ))}

                    <div className="flex flex-wrap items-center text-foreground mt-4 relative text-sm sm:text-base">
                      <span className="mr-2 shrink-0">host@agentcoin:~$</span>

                      <div className="relative flex-grow flex items-center min-h-[1.5rem]" onClick={() => inputRef.current?.focus()}>
                        <span className="whitespace-pre break-all">{input}</span>
                        <span className="w-2.5 h-5 bg-foreground inline-block animate-pulse shrink-0 ml-[1px]"></span>

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

                  <div className="mt-3 border-t border-foreground/15 pt-2.5 space-y-2">
                    <div className="overflow-x-auto custom-scrollbar pb-1">
                      <div className="flex min-w-max items-center gap-2 text-[9px] uppercase tracking-[0.16em]">
                        <button
                          onClick={openWorkflowModal}
                          className="border border-foreground/20 px-2.5 py-1.5 transition-colors hover:bg-foreground hover:text-background"
                        >
                          {tWork("btn_new_workflow")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowComposeTaskRouting((prev) => !prev)}
                          className="border border-foreground/20 px-2.5 py-1.5 transition-colors hover:bg-foreground hover:text-background"
                        >
                          {composeRoutingButtonLabel}
                        </button>
                        <label className="cursor-pointer border border-foreground/20 px-2.5 py-1.5 text-center transition-colors hover:bg-foreground hover:text-background">
                          {tWork("local_multimodal_add_files")}
                          <input type="file" multiple className="hidden" onChange={(e) => { void handleMultimodalFilesSelected(e); }} />
                        </label>
                        <button
                          className="border border-foreground/20 px-2.5 py-1.5 transition-colors hover:bg-foreground hover:text-background disabled:opacity-40"
                          onClick={() => {
                            openClearComposeAttachmentsGuard();
                          }}
                          disabled={localMultimodalAttachments.length === 0}
                        >
                          {tWork("local_multimodal_clear_files")}
                        </button>
                        <button
                          className="bg-foreground text-background px-3 py-1.5 transition-opacity hover:opacity-80 disabled:opacity-50"
                          onClick={() => {
                            void handleDispatchMultimodalTask();
                          }}
                          disabled={localActionBusyKey === "dispatch-task"}
                        >
                          {tWork("local_multimodal_dispatch")}
                        </button>
                      </div>
                    </div>

                    {composeTaskRoutingVisible && (
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(220px,260px)_minmax(0,1fr)]">
                        <select
                          className="bg-foreground/5 border border-foreground/30 px-2.5 py-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-[11px]"
                          value={workflowTargetSelectValue}
                          onChange={(e) => handleWorkflowTargetSelection(e.target.value)}
                        >
                          <option value="">{tWork("local_multimodal_kind_auto_label")}</option>
                          {workflowTargetOptions.map((option) => (
                            <option key={option} value={option}>{option}</option>
                          ))}
                          <option value={WORKFLOW_TARGET_CUSTOM_VALUE}>{tWork("local_multimodal_kind_custom_option")}</option>
                        </select>

                        {showCustomWorkflowTargetInput ? (
                          <input
                            type="text"
                            className="bg-foreground/5 border border-foreground/30 px-2.5 py-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-[11px]"
                            value={showCustomWorkflowTargetInput ? normalizedLocalMultimodalKind : customLocalMultimodalKind}
                            onChange={(e) => handleCustomWorkflowTargetChange(e.target.value)}
                            placeholder={tWork("local_multimodal_kind_custom_placeholder")}
                          />
                        ) : (
                          <div className="hidden sm:block" />
                        )}
                      </div>
                    )}

                    <div className="terminal-compose-shell relative overflow-hidden border border-foreground/25">
                      <div className="pointer-events-none absolute left-3 top-3 z-[1] text-sm text-foreground/45">&gt;</div>
                      <textarea
                        className="terminal-compose-textarea custom-scrollbar min-h-[112px] w-full resize-none border-0 bg-transparent py-3 pl-8 pr-3 text-sm leading-6 outline-none"
                        value={localMultimodalPrompt}
                        onChange={(e) => setLocalMultimodalPrompt(e.target.value)}
                        placeholder={tWork("local_multimodal_prompt_placeholder")}
                        spellCheck={false}
                      />
                    </div>

                    {localMultimodalAttachments.length > 0 && (
                      <div className="flex max-h-16 flex-wrap gap-1.5 overflow-y-auto custom-scrollbar pr-1">
                        {localMultimodalAttachments.map((item) => (
                          <button
                            key={item.id}
                            className="border border-foreground/20 px-2 py-0.5 text-[9px] normal-case tracking-normal hover:bg-foreground/10"
                            onClick={() => {
                              setLocalMultimodalAttachments((prev) => prev.filter((entry) => entry.id !== item.id));
                            }}
                          >
                            {tWork("local_multimodal_remove_file")}: {item.name}
                          </button>
                        ))}
                      </div>
                    )}

                    {(localMultimodalError || localMultimodalNotice) && (
                      <div className="flex justify-end">
                        <div className={`max-w-[min(100%,420px)] animate-[fade-in_0.18s_ease-out] border px-2.5 py-1.5 text-[9px] normal-case tracking-normal ${localMultimodalError ? 'border-foreground/35 bg-foreground text-background font-bold' : 'border-green-400/35 bg-green-400/10 text-green-300'}`}>
                          {localMultimodalError || localMultimodalNotice}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex min-h-0 flex-col">
                  <div className="relative flex min-h-0 flex-1 flex-col border-2 border-foreground bg-foreground/[0.03] p-4 pt-10 shadow-[0_0_28px_rgba(255,255,255,0.05)]">
                    <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold z-10">
                      {tWork("ai_subsystem")}
                    </div>

                    <div className="mt-2 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto custom-scrollbar pr-1">
                      <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                        <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-80">
                          <span>{tWork("ai_subsystem")}</span>
                          <span>{tWork("local_managed_summary", { registrations: localManagedRegistrations.length, running: runningRegistrations })}</span>
                        </div>
                        {aiSubsystemCards.length > 0 && (
                          <div className="space-y-2 rounded-sm border border-foreground/10 bg-black/20 p-2.5 text-[10px] normal-case tracking-normal">
                            <div className="flex items-center justify-between gap-3">
                              <span className="opacity-80">
                                {selectedComposeAgentRegistrationIds.length > 0
                                  ? tWork("ai_subsystem_selected_count", { count: selectedComposeAgentRegistrationIds.length })
                                  : tWork("ai_subsystem_select_auto_hint")}
                              </span>
                              {selectedComposeAgentRegistrationIds.length > 0 && (
                                <button
                                  type="button"
                                  className="opacity-75 transition-opacity hover:opacity-100"
                                  onClick={() => setSelectedComposeAgentRegistrationIds([])}
                                >
                                  {tWork("ai_subsystem_clear_selection")}
                                </button>
                              )}
                            </div>
                            <div className="opacity-55">{tWork("ai_subsystem_multi_hint")}</div>
                          </div>
                        )}
                        {renderAiSubsystemCards({
                          selectable: true,
                          selectedIds: selectedComposeAgentRegistrationIds,
                          onToggleSelection: (agentId) => {
                            setSelectedComposeAgentRegistrationIds((prev) => {
                              if (prev.includes(agentId)) {
                                return prev.filter((id) => id !== agentId);
                              }

                              return [...prev, agentId];
                            });
                          },
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );

            const nodeWindowContent = (
              <div className="h-full">
                <div className="border-2 border-foreground bg-foreground/[0.03] relative flex flex-col p-4 pt-10 h-full shadow-[0_0_28px_rgba(255,255,255,0.05)]">
                  <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold flex justify-between w-full items-center z-10">
                    <span>{tWork("sys_info_label")}</span>
                    <div className="flex flex-wrap gap-4 justify-end">
                      <button 
                        onClick={() => setShowWorkflowModal(true)}
                        className="hover:underline opacity-80 hover:opacity-100"
                      >
                        {tWork("btn_new_workflow", { defaultValue: "[ NEW_WORKFLOW ]" })}
                      </button>
                      <button 
                        onClick={() => {
                           setActiveWorkspaceWindow("swarm");
                           if (localNodeOnline && localAttachReady) {
                             void handleRefreshRemotePeers();
                           }
                        }}
                        className="hover:underline opacity-80 hover:opacity-100"
                      >
                        {tWork("node_open_swarm")}
                      </button>
                      <button 
                        onClick={() => {
                           setActiveWorkspaceWindow("wallet");
                           if (localNodeOnline && localAttachReady) {
                             void refreshLedgerState();
                           }
                        }}
                        className="hover:underline opacity-80 hover:opacity-100"
                      >
                        {tWork("node_open_wallet")}
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
                            {localServices.length > 0 && <div>{tWork("node_services_summary", { count: localServices.length })}</div>}
                            {localCapabilities.length > 0 && <div>{tWork("node_capabilities_summary", { count: localCapabilities.length })}</div>}
                            {(localManagedRegistrations.length > 0 || localAcpSessions.length > 0) && (
                              <div>{tWork("local_runtime_summary", { registrations: localManagedRegistrations.length, sessions: localAcpSessions.length })}</div>
                            )}
                            <div className="normal-case tracking-normal opacity-70">{tWork("local_node_auto_attach_note")}</div>
                            <div className="normal-case tracking-normal opacity-70">{tWork("node_scope_note")}</div>
                            {localNodeError && <div className="text-red-400 normal-case tracking-normal">{localNodeError}</div>}
                            {localRuntimeError && <div className="text-red-400 normal-case tracking-normal">{localRuntimeError}</div>}
                          </div>

                          <div className="flex justify-end gap-3">
                            <button
                              className="border border-foreground/20 px-4 py-1 text-xs hover:bg-foreground/10 disabled:opacity-50"
                              onClick={() => {
                                openDisconnectLocalNodeGuard();
                              }}
                              disabled={!localAttachReady}
                            >
                              {tWork("disconnect")}
                            </button>
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
                              disabled={!localNodeOnline || localDiscoveryBusy}
                            >
                              {tWork("local_node_attach")}
                            </button>
                          </div>
                        </div>
                      </div>

                      <div className="flex-grow relative flex flex-col">
                        {isDiscovering ? (
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
                              <div className="flex flex-col gap-2 text-[10px] uppercase tracking-[0.18em] opacity-80 sm:flex-row sm:items-center sm:justify-between">
                                <span>{tWork("discover_agents")}</span>
                                <button
                                  onClick={() => {
                                    void handleDiscoverAgents();
                                  }}
                                  className="text-left hover:underline disabled:opacity-50 sm:text-right"
                                  disabled={localDiscoveryBusy}
                                >
                                  {tWork("local_runtime_refresh")}
                                </button>
                              </div>
                              <div className="text-[10px] uppercase tracking-[0.14em] opacity-70">
                                {tWork("local_node_discovery_summary", { count: localDiscoveryItems.length })}
                              </div>
                              <div className="space-y-3">
                                {localDiscoveryItems.length > 0 ? localDiscoveryItems.map((item) => {
                                  const registration = managedRegistrationForDiscovery(item.id, localManagedRegistrations);
                                  const session = registration ? acpSessionForRegistration(registration.registration_id, localAcpSessions) : undefined;
                                  const canRegister = !registration && (item.type === "local-cli-agent" || Boolean(item.agentcoin_compatibility?.attachable_today));
                                  const status: AiSubsystemCardStatus = session
                                    ? "open"
                                    : registration
                                      ? String(registration.status || "").trim().toLowerCase() === "running"
                                        ? "running"
                                        : "registered"
                                      : canRegister
                                        ? "attachable"
                                        : "inspect";
                                  const statusMeta = aiSubsystemStatusMeta[status];
                                  const iconKey = preservedAiIconKeyForIdentity(
                                    aiSubsystemIdentity(item.id, item.family, item.title, item.type),
                                  );
                                  const protocols = (
                                    registration?.protocols?.length
                                      ? registration.protocols
                                      : item.protocols?.length
                                        ? item.protocols
                                        : []
                                  ).join(" / ");

                                  return (
                                    <div key={item.id} className="group flex justify-between items-start gap-4 bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm hover:border-foreground/35 hover:bg-foreground/15 transition-all">
                                      <div className="flex min-w-0 items-start gap-3">
                                        {renderAiCardVisual({
                                          icon: preservedAiIcon(iconKey),
                                          glyph: aiSubsystemGlyph(discoveryBadge(item), statusMeta.code),
                                          status,
                                        })}
                                        <div className="min-w-0 space-y-1">
                                          <div className="text-sm font-bold truncate">{item.title}</div>
                                          <div className="text-[10px] opacity-70 uppercase tracking-widest truncate">
                                            {discoverySummary(item) || item.type || "-"}
                                          </div>
                                          <div className="text-[10px] opacity-60 truncate">{item.id}</div>
                                          <div className="text-[10px] opacity-65 truncate">
                                            {protocols || tWork("remote_peers_no_protocols")}
                                          </div>
                                        </div>
                                      </div>
                                      <div className="shrink-0 flex flex-col items-end gap-2">
                                        <div className={`text-[10px] uppercase tracking-[0.16em] font-bold ${statusMeta.toneClass}`}>
                                          {statusMeta.label}
                                        </div>
                                        {registration ? (
                                          <button
                                            className="text-[10px] uppercase tracking-widest opacity-60 cursor-default"
                                            disabled
                                          >
                                            {tWork("local_registered_badge")}
                                          </button>
                                        ) : canRegister ? (
                                          <button
                                            className="bg-foreground text-background font-bold px-3 py-1 hover:opacity-80 transition-opacity text-[10px] uppercase tracking-widest disabled:opacity-50"
                                            onClick={() => {
                                              void handleRegisterDiscoveredAgent(item);
                                            }}
                                            disabled={localActionBusyKey === `register:${item.id}` || !localNodeToken.trim()}
                                          >
                                            {tWork("local_register")}
                                          </button>
                                        ) : (
                                          <div className="text-[10px] uppercase tracking-widest opacity-55">
                                            {tWork("ai_subsystem_status_inspect")}
                                          </div>
                                        )}
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
                                  const discovery = String(registration.discovered_id || "").trim()
                                    ? localDiscoveryById.get(String(registration.discovered_id || "").trim())
                                    : undefined;
                                  const session = acpSessionForRegistration(registration.registration_id, localAcpSessions);
                                  const supportsAcp = (registration.protocols || []).includes("acp");
                                  const card = aiSubsystemCardsById.get(registration.registration_id);
                                  const fallbackStatus: AiSubsystemCardStatus = session
                                    ? "open"
                                    : String(registration.status || "").trim().toLowerCase() === "running"
                                      ? "running"
                                      : "registered";
                                  const status = card?.status || fallbackStatus;
                                  const statusMeta = aiSubsystemStatusMeta[status];
                                  const summary = card?.summary || aiSubsystemSummaryForManaged(registration, discovery, session);
                                  const glyph = card?.glyph || aiSubsystemGlyph(
                                    discovery ? discoveryBadge(discovery) : managedRegistrationBadge(registration),
                                    aiSubsystemStatusMeta[status].code,
                                  );
                                  const displayName = card?.name || registration.title || discovery?.title || registration.registration_id;

                                  return (
                                    <div key={registration.registration_id} className="group flex justify-between items-start gap-4 bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm hover:border-foreground/35 hover:bg-foreground/15 transition-all">
                                      <div className="flex min-w-0 items-start gap-3">
                                        {renderAiCardVisual({
                                          icon: card?.icon,
                                          glyph,
                                          status,
                                        })}
                                        <div className="min-w-0 space-y-1">
                                          <div className="text-sm font-bold truncate">{displayName}</div>
                                          <div className="text-[10px] opacity-70 uppercase tracking-widest truncate">{summary || tWork("remote_peers_no_protocols")}</div>
                                          <div className="text-[10px] opacity-60 truncate">{registration.registration_id}</div>
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
                                      </div>
                                      <div className="shrink-0 flex flex-col items-end gap-2">
                                        <div className={`text-[10px] uppercase tracking-[0.16em] font-bold ${statusMeta.toneClass}`}>
                                          {statusMeta.label}
                                        </div>
                                        {registration.status === "running" ? (
                                          <button
                                            className="hover:underline text-[10px] uppercase tracking-widest disabled:opacity-50"
                                            onClick={() => {
                                              openStopRegistrationGuard(registration);
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
                                    type="button"
                                    onClick={() => setShowAcpAdvancedConfig((prev) => !prev)}
                                    className="text-left hover:underline sm:text-right"
                                  >
                                    {showAcpAdvancedConfig ? tWork("local_acp_hide_advanced") : tWork("local_acp_show_advanced")}
                                  </button>
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
                              {!showAcpAdvancedConfig && (
                                <div className="border border-foreground/10 bg-foreground/5 p-3 text-[10px] normal-case tracking-normal opacity-70">
                                  {tWork("local_acp_advanced_hidden_hint")}
                                </div>
                              )}
                              <div className="space-y-3">
                                {localAcpSessions.length > 0 ? localAcpSessions.map((session) => {
                                  const registration = localManagedRegistrations.find((item) => item.registration_id === session.registration_id);
                                  const currentInputs = localSessionTaskInputs[session.session_id] || {
                                    taskId: session.last_task_request_intent?.mapping?.agentcoin_task_id || "",
                                    serverSessionId: inferAcpServerSessionId(session),
                                  };
                                  const inferredServerSessionId = inferAcpServerSessionId(session);
                                  const listedServerSessions = Array.isArray(session.listed_server_sessions) ? session.listed_server_sessions : [];
                                  const loadedServerSessionId = String(session.loaded_server_session_id || "").trim();
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
                                            {showAcpAdvancedConfig && (
                                              <>
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

                                                {loadedServerSessionId && (
                                                  <div className="text-[10px] opacity-65 normal-case tracking-normal break-all">
                                                    {tWork("local_acp_loaded_session")}: {loadedServerSessionId}
                                                  </div>
                                                )}

                                                <div className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal opacity-85 space-y-2">
                                                  <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_session_history_label")}</div>
                                                  {listedServerSessions.length > 0 ? listedServerSessions.map((listedSession) => {
                                                    const listedSessionSummary = acpListedSessionSummary(listedSession);
                                                    const listActionKey = `load-session:${session.session_id}:${listedSession.sessionId}`;
                                                    return (
                                                      <div key={listedSession.sessionId} className="border border-foreground/10 bg-black/20 p-2 space-y-2">
                                                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                                          <div className="min-w-0">
                                                            <div className="truncate">{listedSession.title || listedSession.sessionId}</div>
                                                            <div className="mt-1 break-all opacity-65">{listedSession.sessionId}</div>
                                                          </div>
                                                          <button
                                                            className="border border-foreground/20 px-2 py-1 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                                            onClick={() => {
                                                              void handleLoadAcpServerSession(session, listedSession.sessionId);
                                                            }}
                                                            disabled={session.status !== "open" || localActionBusyKey === listActionKey}
                                                          >
                                                            {loadedServerSessionId === listedSession.sessionId ? tWork("local_acp_session_loaded") : tWork("local_acp_session_load")}
                                                          </button>
                                                        </div>
                                                        {listedSessionSummary && <div className="break-all opacity-65">{listedSessionSummary}</div>}
                                                      </div>
                                                    );
                                                  }) : (
                                                    <div className="opacity-65">{tWork("local_acp_session_history_empty")}</div>
                                                  )}
                                                </div>

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
                                              </>
                                            )}

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

                                      {showAcpAdvancedConfig && (
                                      <div className="w-full shrink-0 xl:w-[220px]">
                                        <div className="border border-foreground/10 bg-black/20 p-3 space-y-2">
                                          <div className="text-[10px] uppercase tracking-[0.14em] opacity-65 normal-case">
                                            {tWork("local_acp_controls_hint")}
                                          </div>
                                          <button
                                            className="w-full border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                            onClick={() => {
                                              void handleListAcpServerSessions(session);
                                            }}
                                            disabled={localActionBusyKey === `list-sessions:${session.session_id}` || session.status !== "open"}
                                          >
                                            {tWork("local_acp_session_list")}
                                          </button>
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
                                              openCloseAcpSessionGuard(session, registration);
                                            }}
                                            disabled={localActionBusyKey === `close-acp:${session.session_id}`}
                                          >
                                            {tWork("local_acp_close")}
                                          </button>
                                        </div>
                                      </div>
                                      )}
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
                          renderAiSubsystemCards()
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-8 text-xs text-muted-foreground border-t border-foreground/30 pt-4 shrink-0">
                    <p>{tWork("clear_hint_prefix")}<span className="text-foreground font-bold">clear</span>{tWork("clear_hint_suffix")}</p>
                  </div>
                </div>
              </div>
            );

            const swarmWindowContent = (
              <div className="h-full">
                <div className="border-2 border-foreground bg-foreground/[0.03] relative flex h-full flex-col p-4 pt-10 shadow-[0_0_28px_rgba(255,255,255,0.05)]">
                  <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold flex justify-between w-full items-center z-10">
                    <span>{tWork("window_swarm")}</span>
                    <div className="flex gap-4">
                      <button
                        onClick={openWorkflowModal}
                        className="hover:underline opacity-80 hover:opacity-100"
                      >
                        {tWork("swarm_open_workflow")}
                      </button>
                      <button
                        onClick={() => {
                          void handleRefreshRemotePeers();
                        }}
                        disabled={remotePeersBusy}
                        className="hover:underline opacity-80 hover:opacity-100 disabled:opacity-50"
                      >
                        {tWork("remote_peers_refresh")}
                      </button>
                      <button
                        onClick={() => {
                          void handleSyncRemotePeers();
                        }}
                        disabled={!localAttachReady || remotePeerSyncBusy}
                        className="hover:underline opacity-80 hover:opacity-100 disabled:opacity-50"
                      >
                        {tWork("remote_peers_sync")}
                      </button>
                    </div>
                  </div>

                  <div className="mt-2 flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar pr-1">
                    {localNodeOnline || swarmGraphReady || swarmAttentionMessage ? (
                      <div className="space-y-4">
                        <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                            <div>
                              <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("swarm_console_title")}</div>
                              <div className="mt-2 text-sm leading-6 opacity-85">{tWork("swarm_console_live")}</div>
                            </div>
                            <div className="text-[10px] uppercase tracking-[0.14em] opacity-75">
                              {tWork("remote_peers_summary", { peers: remotePeers.length, cards: remotePeerCards.length, health: remotePeerHealth.length })}
                            </div>
                          </div>
                          <div className="text-xs leading-6 opacity-70">{tWork("remote_peers_config_hint")}</div>

                          {swarmAttentionMessage && (
                            <div className="border border-foreground bg-foreground text-background px-3 py-2 text-[10px] normal-case tracking-normal font-bold">
                              {swarmAttentionMessage}
                            </div>
                          )}
                        </div>

                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("swarm_metric_peers")}</div>
                            <div className="mt-2 text-2xl font-bold">{remotePeers.length}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("swarm_metric_cards")}</div>
                            <div className="mt-2 text-2xl font-bold">{remotePeerCards.length}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("swarm_metric_review")}</div>
                            <div className="mt-2 text-2xl font-bold">{swarmTrustReviewCount}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("swarm_metric_blacklisted")}</div>
                            <div className="mt-2 text-2xl font-bold">{swarmBlacklistedCount}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("swarm_metric_cooldown")}</div>
                            <div className="mt-2 text-2xl font-bold">{swarmCooldownCount}</div>
                          </div>
                        </div>

                        <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("remote_peers_label")}</div>
                          {swarmPeers.length > 0 ? (
                            <div className="space-y-3">
                              {swarmPeers.map(({ peerId, peer, card, health }) => {
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
                                  <div key={peerId} className="flex flex-col gap-3 border border-foreground/10 bg-black/20 p-4 rounded-sm xl:flex-row xl:items-start xl:justify-between">
                                    <div className="min-w-0 flex items-start gap-3">
                                      <div className="w-10 h-10 shrink-0 border border-foreground/30 bg-black/50 flex items-center justify-center text-[11px] font-bold tracking-[0.18em]">
                                        {peerId.slice(0, 3).toUpperCase()}
                                      </div>
                                      <div className="min-w-0 space-y-1">
                                        <div className="text-sm font-bold truncate">{peer?.name || card?.card?.name || peerId}</div>
                                        <div className="text-[10px] opacity-70 uppercase tracking-widest break-all">{peer?.overlay_endpoint || peer?.url || tWork("swarm_value_unknown")}</div>
                                        {card?.card?.description && <div className="text-[10px] opacity-65 break-words">{card.card.description}</div>}
                                        {health?.last_error && <div className="text-[10px] text-red-400 break-words">{health.last_error}</div>}
                                      </div>
                                    </div>

                                    <div className="grid grid-cols-1 gap-3 text-[10px] uppercase tracking-[0.14em] opacity-80 xl:min-w-[240px]">
                                      <div>
                                        <div className="opacity-55">{tWork("swarm_health_label")}</div>
                                        <div className="mt-1 normal-case tracking-normal opacity-100">{healthState}</div>
                                      </div>
                                      <div>
                                        <div className="opacity-55">{tWork("swarm_trust_label")}</div>
                                        <div className="mt-1 normal-case tracking-normal opacity-100">{trustState}</div>
                                      </div>
                                      <div>
                                        <div className="opacity-55">{tWork("swarm_protocols_label")}</div>
                                        <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{card?.card?.protocols?.slice(0, 3).join(" / ") || tWork("remote_peers_no_protocols")}</div>
                                      </div>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("remote_peers_empty")}</div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="flex h-full items-center justify-center">
                        <div className="max-w-xl border-2 border-foreground bg-foreground/[0.03] px-6 py-8 text-center shadow-[0_0_30px_rgba(255,255,255,0.08)]">
                          <div className="text-[10px] uppercase tracking-[0.22em] opacity-60">{tWork("window_swarm")}</div>
                          <div className="mt-4 text-lg font-bold tracking-[0.08em]">{tWork("swarm_empty_title")}</div>
                          <p className="mt-4 text-sm leading-7 opacity-80">{tWork("swarm_empty_body")}</p>

                          <div className="mt-6 flex flex-wrap justify-center gap-3">
                            <button
                              onClick={() => setActiveWorkspaceWindow("node")}
                              className="border border-foreground/20 px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:bg-foreground hover:text-background transition-none"
                            >
                              {tWork("swarm_open_node")}
                            </button>
                            <button
                              onClick={() => {
                                void handleRefreshRemotePeers();
                              }}
                              disabled={remotePeersBusy}
                              className="bg-foreground text-background px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:opacity-80 disabled:opacity-50"
                            >
                              {tWork("remote_peers_refresh")}
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );

            const walletWindowProps = {
              tWork,
              header: {
                localLedgerBusy,
                walletLedgerReady,
                localLedgerError,
                onRefreshLedger: () => {
                  void refreshLedgerState();
                },
                onOpenNode: () => setActiveWorkspaceWindow("node"),
              },
              summary: {
                walletReconciliationStatus,
                walletLastUpdated,
                walletRecommendedActions,
                walletActionBusyKey,
                walletActionError,
                walletActionNotice,
                onRecommendedAction: (action: string) => {
                  void handleWalletRecommendedAction(action);
                },
                getWalletRecommendedActionLabel,
              },
              receiptPanel: {
                walletReceiptIssueChallengeId,
                walletReceiptWorkflowName,
                walletReceiptIssuePayer,
                walletReceiptIssueTxHash,
                workflowTargetOptions,
                walletReceiptDraft,
                walletReceiptResult,
                onWalletReceiptIssueChallengeIdChange: setWalletReceiptIssueChallengeId,
                onWalletReceiptWorkflowNameChange: setWalletReceiptWorkflowName,
                onWalletReceiptIssuePayerChange: setWalletReceiptIssuePayer,
                onWalletReceiptIssueTxHashChange: setWalletReceiptIssueTxHash,
                onWalletReceiptDraftChange: setWalletReceiptDraft,
                onIssueReceipt: () => {
                  void handleWalletIssueReceipt();
                },
                onIntrospectReceipt: () => {
                  void handleWalletIntrospectReceipt();
                },
              },
              tokenPanel: {
                walletTokenWorkflowName,
                walletTokenServiceId,
                walletTokenMaxUses,
                walletTokenDraft,
                walletTokenResult,
                onWalletTokenWorkflowNameChange: setWalletTokenWorkflowName,
                onWalletTokenServiceIdChange: setWalletTokenServiceId,
                onWalletTokenMaxUsesChange: setWalletTokenMaxUses,
                onWalletTokenDraftChange: setWalletTokenDraft,
                onIssueToken: () => {
                  void handleWalletIssueRenterToken();
                },
                onIntrospectToken: () => {
                  void handleWalletIntrospectRenterToken();
                },
              },
              relayPanel: {
                walletQueueReceiptId,
                walletQueueStatusFilter,
                walletQueueDelaySeconds,
                walletQueueMaxAttempts,
                walletRelayTimeoutSeconds,
                walletQueueReason,
                walletRelayRpcUrl,
                walletRelayRawTransactionsDraft,
                walletQueueItems,
                walletLatestRelayDisplay,
                walletLatestFailedRelayDisplay,
                walletRelayResult,
                onWalletQueueReceiptIdChange: setWalletQueueReceiptId,
                onWalletQueueStatusFilterChange: setWalletQueueStatusFilter,
                onWalletQueueDelaySecondsChange: setWalletQueueDelaySeconds,
                onWalletQueueMaxAttemptsChange: setWalletQueueMaxAttempts,
                onWalletRelayTimeoutSecondsChange: setWalletRelayTimeoutSeconds,
                onWalletQueueReasonChange: setWalletQueueReason,
                onWalletRelayRpcUrlChange: setWalletRelayRpcUrl,
                onWalletRelayRawTransactionsDraftChange: setWalletRelayRawTransactionsDraft,
                onRelayQueueRefresh: handleWalletRelayQueueRefreshClick,
                onRelayLoadLatest: handleWalletRelayLatestClick,
                onRelayLoadLatestFailed: handleWalletRelayLatestFailedClick,
                onRelayLoadReplayHelper: handleWalletReplayHelperClick,
                onRelayBuildProof: handleWalletBuildProofClick,
                onRelayBuildRpcPlan: handleWalletBuildRpcPlanClick,
                onRelayQueueSubmit: handleWalletRelayQueueSubmitClick,
                onRelayQueueItemAction: handleWalletRelayQueueItemClick,
              },
              metrics: {
                walletRunningRelays,
                walletDeadLetters,
                walletTokenTotal,
                walletRemainingUses,
                walletRequeueCount,
              },
              ledger: {
                walletQueueEntries,
                walletUsageItems,
                walletTokenItems,
                getWalletQueueLabel,
              },
              helpers: {
                prettyJson,
                prettyDisplayJson,
              },
            };

            const walletWindowContent = (
              <WalletWindow {...walletWindowProps} />
            );

            const communityWindowContent = (
              <div className="h-full">
                <div className="border-2 border-foreground bg-foreground/[0.03] relative flex h-full flex-col p-4 pt-10 shadow-[0_0_28px_rgba(255,255,255,0.05)]">
                  <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold flex justify-between w-full items-center z-10">
                    <span>{tWork("window_community")}</span>
                  </div>

                  <div className="mt-2 flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar pr-1">
                    {communityWindowReady ? (
                      <div className="space-y-4">
                        <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                            <div>
                              <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("community_console_title")}</div>
                              <div className="mt-2 text-sm leading-6 opacity-85">{tWork("community_console_live")}</div>
                            </div>
                            <div className="text-[10px] uppercase tracking-[0.14em] opacity-75">
                              {tWork("window_community_summary_live", { catalog: communityCatalogCount, peers: communityDirectory.length })}
                            </div>
                          </div>
                          <div className="text-xs leading-6 opacity-70">{tWork("community_readonly_note")}</div>
                        </div>

                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("community_metric_services")}</div>
                            <div className="mt-2 text-2xl font-bold">{communityServices.length}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("community_metric_capabilities")}</div>
                            <div className="mt-2 text-2xl font-bold">{communityCapabilities.length}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("community_metric_operators")}</div>
                            <div className="mt-2 text-2xl font-bold">{communityDirectory.length}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("community_metric_aligned")}</div>
                            <div className="mt-2 text-2xl font-bold">{communityAlignedCount}</div>
                          </div>
                          <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                            <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("community_metric_review")}</div>
                            <div className="mt-2 text-2xl font-bold">{communityReviewCount}</div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                          <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("community_local_catalog_label")}</div>
                            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                              <div className="space-y-2">
                                <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("community_services_label")}</div>
                                {communityServices.length > 0 ? (
                                  <div className="space-y-2">
                                    {communityServices.slice(0, 5).map((service: any, index) => (
                                      <div key={String(service?.service_id || service?.id || index)} className="border border-foreground/10 bg-black/20 p-3">
                                        <div className="text-sm font-bold break-words">{String(service?.service_id || service?.name || tWork("community_value_unknown"))}</div>
                                        <div className="mt-2 text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("community_service_price_label")}</div>
                                        <div className="mt-1 text-xs opacity-85 break-words">{String(service?.price_per_call || service?.price || 0)} {String(service?.price_asset || service?.asset || "")}</div>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("community_empty_services")}</div>
                                )}
                              </div>

                              <div className="space-y-2">
                                <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("community_capabilities_label")}</div>
                                {communityCapabilities.length > 0 ? (
                                  <div className="space-y-2">
                                    {communityCapabilities.slice(0, 5).map((capability: any, index) => (
                                      <div key={String(capability?.id || capability?.name || index)} className="border border-foreground/10 bg-black/20 p-3">
                                        <div className="text-sm font-bold break-words">{String(capability?.id || capability?.name || tWork("community_value_unknown"))}</div>
                                        <div className="mt-2 text-xs opacity-80 break-words">{String(capability?.description || capability?.summary || tWork("community_value_unknown"))}</div>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("community_empty_capabilities")}</div>
                                )}
                              </div>
                            </div>
                          </div>

                          <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                            <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-70">
                              <span>{tWork("community_directory_label")}</span>
                              <span>{communityProtocolCount}</span>
                            </div>
                            {communityDirectory.length > 0 ? (
                              <div className="space-y-2">
                                {communityDirectory.slice(0, 6).map(({ peerId, peer, card, health }) => {
                                  const trustState = card?.identity_trust?.requires_review
                                    ? tWork("swarm_trust_review")
                                    : card?.identity_trust?.aligned
                                      ? tWork("swarm_trust_aligned")
                                      : tWork("swarm_trust_unknown");
                                  const protocolList = Array.from(new Set([
                                    ...(Array.isArray(card?.card?.protocols) ? card.card.protocols : []),
                                    ...(Array.isArray(peer?.tags) ? peer.tags : []),
                                  ].map((value) => String(value || "").trim()).filter(Boolean)));

                                  return (
                                    <div key={peerId} className="border border-foreground/10 bg-black/20 p-3 space-y-3">
                                      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                                        <div className="min-w-0">
                                          <div className="text-sm font-bold break-words">{peer?.name || card?.card?.name || peerId}</div>
                                          <div className="mt-1 text-[10px] uppercase tracking-[0.14em] opacity-55 break-all">{peer?.overlay_endpoint || peer?.url || tWork("community_value_unknown")}</div>
                                          {card?.card?.description && <div className="mt-2 text-xs opacity-80 break-words">{card.card.description}</div>}
                                          {health?.last_error && <div className="mt-2 text-xs text-red-400 break-words">{String(health.last_error)}</div>}
                                        </div>
                                        <div className="grid grid-cols-1 gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75 sm:min-w-[220px]">
                                          <div>
                                            <div className="opacity-55">{tWork("community_trust_label")}</div>
                                            <div className="mt-1 normal-case tracking-normal opacity-100">{trustState}</div>
                                          </div>
                                          <div>
                                            <div className="opacity-55">{tWork("community_protocols_label")}</div>
                                            <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{protocolList.length > 0 ? protocolList.slice(0, 4).join(" / ") : tWork("community_value_unknown")}</div>
                                          </div>
                                          {health?.status && (
                                            <div>
                                              <div className="opacity-55">{tWork("swarm_health_label")}</div>
                                              <div className="mt-1 normal-case tracking-normal opacity-100">{String(health.status)}</div>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("community_empty_directory")}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex h-full items-center justify-center">
                        <div className="max-w-xl border-2 border-foreground bg-foreground/[0.03] px-6 py-8 text-center shadow-[0_0_30px_rgba(255,255,255,0.08)]">
                          <div className="text-[10px] uppercase tracking-[0.22em] opacity-60">{tWork("window_community")}</div>
                          <div className="mt-4 text-lg font-bold tracking-[0.08em]">{tWork("community_empty_title")}</div>
                          <p className="mt-4 text-sm leading-7 opacity-80">{tWork("community_empty_body")}</p>

                          <div className="mt-6 flex flex-wrap justify-center gap-3">
                            <button
                              onClick={() => setActiveWorkspaceWindow("node")}
                              className="border border-foreground/20 px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:bg-foreground hover:text-background transition-none"
                            >
                              {tWork("community_open_node")}
                            </button>
                            <button
                              onClick={() => setActiveWorkspaceWindow("swarm")}
                              className="bg-foreground text-background px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:opacity-80"
                            >
                              {tWork("community_open_swarm")}
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
            const plannedWindowContent = (
              <div className="flex h-full items-center justify-center">
                <div className="max-w-2xl border-2 border-foreground bg-foreground/[0.03] px-6 py-8 text-center shadow-[0_0_30px_rgba(255,255,255,0.08)]">
                  <div className="flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.22em] opacity-60">
                    <span>{activeWindowMeta.label}</span>
                    <span className="border border-foreground/20 bg-foreground/5 px-2 py-1">{tWork("window_planned")}</span>
                  </div>

                  <div className="mt-4 text-lg font-bold tracking-[0.08em]">{activePlannedWindow.title}</div>
                  <p className="mt-4 text-sm leading-7 opacity-80">{activePlannedWindow.body}</p>

                  <div className="mt-6 grid gap-3 text-left md:grid-cols-2">
                    <div className="border border-foreground/20 bg-black/20 p-4">
                      <div className="text-[10px] uppercase tracking-[0.18em] opacity-55">{tWork("planned_window_status_label")}</div>
                      <div className="mt-2 text-sm leading-6 opacity-85">{activePlannedWindow.status}</div>
                    </div>

                    <div className="border border-foreground/20 bg-black/20 p-4">
                      <div className="text-[10px] uppercase tracking-[0.18em] opacity-55">{tWork("planned_window_next_label")}</div>
                      <div className="mt-2 text-sm leading-6 opacity-85">{activePlannedWindow.next}</div>
                    </div>
                  </div>

                  <div className="mt-6 border border-foreground/20 bg-foreground/6 px-4 py-3 text-left text-xs leading-6 opacity-75">
                    {tWork("planned_window_phase_note")}
                  </div>
                </div>
              </div>
            );

  const getWindowRailCopy = (windowId: WorkspaceWindowId) => {
    switch (windowId) {
      case "compose":
        return {
          description: tWork("window_compose_hint"),
          summary:
            localMultimodalAttachments.length > 0
              ? tWork("window_compose_summary_draft", { count: localMultimodalAttachments.length })
              : localTasks.length > 0
                ? tWork("window_compose_summary_tasks", { count: localTasks.length })
                : tWork("window_compose_summary_idle"),
        };
      case "node":
        return {
          description: tWork("window_node_hint"),
          summary: localNodeOnline
            ? tWork("window_node_summary_online", {
                registrations: localManagedRegistrations.length,
                sessions: localAcpSessions.length,
              })
            : tWork("window_node_summary_offline"),
        };
      case "swarm":
        return {
          description: tWork("window_swarm_hint"),
          summary: swarmAttentionMessage
            ? swarmAttentionMessage
            : swarmGraphReady
              ? tWork("window_swarm_summary", {
                  peers: remotePeers.length,
                  cards: remotePeerCards.length,
                })
              : tWork("window_swarm_summary_pending"),
        };
      case "wallet":
        return {
          description: tWork("window_wallet_hint"),
          summary: localLedgerError
            ? localLedgerError
            : paymentOpsSummary || serviceUsageSummary || renterTokenSummary
            ? tWork("window_wallet_summary_live", {
                relays: paymentOpsSummary?.queue_summary?.running || 0,
                tokens: serviceUsageSummary?.active_tokens || renterTokenSummary?.total_tokens || renterTokenSummary?.items?.length || 0,
              })
            : tWork("window_wallet_summary_pending"),
        };
      case "community":
      default:
        return {
          description: tWork("window_community_hint"),
          summary: communityWindowReady
            ? tWork("window_community_summary_live", { catalog: communityCatalogCount, peers: communityDirectory.length })
            : tWork("window_community_summary_pending"),
        };
    }
  };

  const activeWindowRail = getWindowRailCopy(activeWorkspaceWindow);

  const activeWorkspaceContent = activeWorkspaceWindow === "compose"
    ? composeWindowContent
    : activeWorkspaceWindow === "node"
      ? nodeWindowContent
      : activeWorkspaceWindow === "swarm"
        ? swarmWindowContent
      : activeWorkspaceWindow === "wallet"
        ? walletWindowContent
      : activeWorkspaceWindow === "community"
        ? communityWindowContent
      : plannedWindowContent;

  return (
    <div className="min-h-screen h-[100dvh] overflow-hidden bg-background text-foreground font-mono p-4 sm:p-6 selection:bg-foreground selection:text-background transition-colors duration-0 flex flex-col relative z-10">
                <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
                  <div className="flex w-full shrink-0 lg:w-auto" style={sidebarStyle}>
                    <aside ref={sidebarRef} data-tour-target="rail" className="w-full shrink-0 border-2 border-foreground bg-foreground/[0.03] flex flex-col shadow-[0_0_28px_rgba(255,255,255,0.05)] lg:w-[var(--sidebar-width)]">
                      <div className={`border-b border-foreground/30 py-3 text-[10px] uppercase tracking-[0.22em] opacity-75 ${sidebarCompact ? 'px-2' : 'px-4'}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate">{tWork("window_rail_label")}</span>
                          {isDesktopViewport && (
                            <div className="flex items-center gap-1">
                              {!sidebarCompact && (
                                <div className="border border-foreground/15 px-2 py-1 text-[9px] opacity-60">
                                  {sidebarDesktopWidth}px
                                </div>
                              )}
                              <button
                                type="button"
                                onClick={() => resizeSidebarBy(-24)}
                                aria-label={tWork("window_rail_resize_handle")}
                                title={tWork("window_rail_resize_handle")}
                                className={`shrink-0 border border-foreground/20 px-2 py-1 text-[9px] transition-none ${sidebarCompact ? 'hidden' : 'hover:bg-foreground hover:text-background'}`}
                              >
                                -
                              </button>
                              <button
                                type="button"
                                onClick={() => resizeSidebarBy(24)}
                                aria-label={tWork("window_rail_resize_handle")}
                                title={tWork("window_rail_resize_handle")}
                                className={`shrink-0 border border-foreground/20 px-2 py-1 text-[9px] transition-none ${sidebarCompact ? 'hidden' : 'hover:bg-foreground hover:text-background'}`}
                              >
                                +
                              </button>
                              <button
                                type="button"
                                onClick={toggleSidebarCollapsed}
                                aria-label={sidebarCompact ? tWork("window_rail_toggle_expand") : tWork("window_rail_toggle_collapse")}
                                className="shrink-0 border border-foreground/20 px-2 py-1 text-[9px] hover:bg-foreground hover:text-background transition-none"
                              >
                                {sidebarCompact ? ">" : "<"}
                              </button>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className={`flex-1 overflow-y-auto custom-scrollbar space-y-2 ${sidebarCompact ? 'p-2' : 'p-3'}`}>
                      {workspaceWindows.map((windowItem) => {
                        const isActive = activeWorkspaceWindow === windowItem.id;
                        const windowCopy = getWindowRailCopy(windowItem.id);
                        const windowAlerts = getWindowAlerts(windowItem.id);
                        const windowAlertCount = windowAlerts.length;
                        const windowHasCriticalAlert = windowAlerts.some((item) => item.severity === "critical");
                        return (
                          <button
                            key={windowItem.id}
                            onClick={() => setActiveWorkspaceWindow(windowItem.id)}
                            className={`w-full border text-left transition-colors ${sidebarCompact ? 'px-2 py-2' : 'px-3 py-3'} ${isActive ? 'border-foreground bg-foreground text-background' : 'border-foreground/20 bg-foreground/5 hover:bg-foreground/10'} ${windowItem.alert ? 'shadow-[0_0_18px_rgba(255,255,255,0.18)]' : ''}`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className={`font-bold uppercase tracking-[0.18em] ${sidebarCompact ? 'text-[11px] leading-4 break-words' : 'text-xs'}`}>{windowItem.label}</span>
                              {windowAlertCount > 0 && (
                                <span className={`border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.14em] ${isActive ? 'border-background/30 text-background' : windowHasCriticalAlert ? 'border-foreground text-foreground' : 'border-foreground/30 text-foreground/80'}`}>
                                  {tWork("alert_window_count", { count: windowAlertCount })}
                                </span>
                              )}
                            </div>
                            <div className={`mt-2 text-[10px] uppercase tracking-[0.18em] ${isActive ? 'text-background/75' : 'opacity-55'}`}>
                              {windowItem.planned ? tWork("window_planned") : tWork("window_ready")}
                            </div>
                            {!sidebarCompact && (
                              <>
                                <div className={`mt-2 text-[11px] leading-5 normal-case tracking-normal ${isActive ? 'text-background/80' : 'opacity-75'}`}>
                                  {windowCopy.description}
                                </div>
                                <div className={`mt-3 border-t pt-2 text-[10px] normal-case tracking-normal ${isActive ? 'border-background/15 text-background/70' : 'border-foreground/10 opacity-60'}`}>
                                  {windowCopy.summary}
                                </div>
                              </>
                            )}
                          </button>
                        );
                      })}
                      </div>
                    </aside>
                    <div className="relative hidden lg:flex w-5 shrink-0 items-stretch">
                      <div className="pointer-events-none absolute inset-y-3 left-1/2 w-px -translate-x-1/2 bg-foreground/20" />
                      <button
                        type="button"
                        onMouseDown={(event) => {
                          event.preventDefault();
                          setSidebarResizing(true);
                        }}
                        aria-label={tWork("window_rail_resize_handle")}
                        title={tWork("window_rail_resize_handle")}
                        className="absolute inset-y-0 left-1/2 flex w-5 -translate-x-1/2 cursor-col-resize items-center justify-center bg-transparent"
                      >
                        <span className={`flex h-16 w-3 items-center justify-center rounded-full border text-[10px] leading-none transition-none ${sidebarResizing ? 'border-foreground bg-foreground text-background' : 'border-foreground/25 bg-foreground/[0.06] text-foreground/55 hover:border-foreground/45 hover:text-foreground/85'}`}>
                          ||
                        </span>
                      </button>
                    </div>
                  </div>

                  <section className="flex min-h-0 flex-1 flex-col border-2 border-foreground bg-foreground/[0.02] shadow-[0_0_30px_rgba(255,255,255,0.06)]">
                    <div data-tour-target="status" className="relative z-[40] border-b border-foreground/30 px-4 py-3 overflow-x-auto custom-scrollbar lg:overflow-visible">
                      <div className="flex min-w-max items-center gap-2 text-[10px] uppercase tracking-[0.18em] opacity-80">
                        <span className="opacity-55">{tWork("shell_active_window")}</span>
                        <span className="border border-foreground/20 px-2 py-1 bg-foreground/5 font-bold">{activeWindowMeta.label}</span>
                        <span className="border border-foreground/20 px-2 py-1 bg-foreground/5">{tWork("shell_node_state")}: {shellNodeState}</span>
                        <span className="border border-foreground/20 px-2 py-1 bg-foreground/5">{tWork("shell_sessions")}: {localAcpSessions.length}</span>
                        <span className="border border-foreground/20 px-2 py-1 bg-foreground/5">{tWork("shell_tasks")}: {localTasks.length}</span>
                        <span className="opacity-55">{tWork("theme")}</span>
                        <button
                          type="button"
                          onDoubleClick={cycleTheme}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              cycleTheme();
                            }
                          }}
                          className="border border-foreground/20 px-2 py-1 bg-foreground/5 hover:bg-foreground hover:text-background transition-none"
                        >
                          {currentThemeLabel}
                        </button>
                        <span className="ml-1 opacity-55">{tWork("language")}</span>
                        <button
                          type="button"
                          onDoubleClick={cycleLanguage}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              cycleLanguage();
                            }
                          }}
                          className="border border-foreground/20 px-2 py-1 bg-foreground/5 hover:bg-foreground hover:text-background transition-none"
                        >
                          {currentLanguageLabel}
                        </button>
                        <button type="button" onClick={openIntroExperience} className="border border-foreground/20 px-2 py-1 bg-foreground/5 hover:bg-foreground hover:text-background transition-none">
                          {tWork("intro_button")}
                        </button>
                        <div
                          data-tour-target="alerts"
                          className={`relative flex items-center gap-2 border px-2 py-1 ${alertEntries.length > 0 ? 'border-foreground bg-foreground text-background' : 'border-foreground/20 bg-foreground/5'}`}
                          onMouseLeave={() => setHoveredAlertGroupId(null)}
                        >
                          <span>{tWork("shell_alert")}:</span>
                          {alertSummaryGroups.map((group, index) => (
                            <button
                              key={group.id}
                              type="button"
                              onMouseEnter={() => setHoveredAlertGroupId(group.id)}
                              onFocus={() => setHoveredAlertGroupId(group.id)}
                              className="normal-case tracking-normal outline-none"
                            >
                              {group.label}
                              {index < alertSummaryGroups.length - 1 && <span className="px-2 opacity-60">|</span>}
                            </button>
                          ))}

                          {hoveredAlertGroup && (
                            <div className={`absolute right-0 top-full z-[80] mt-2 w-[320px] border px-3 py-3 sm:w-[380px] ${alertPopoverToneClass}`}>
                              <div className="text-[10px] uppercase tracking-[0.18em] opacity-75">{hoveredAlertGroup.label}</div>
                              {hoveredAlertGroup.alerts.length > 0 ? (
                                <div className="mt-3 space-y-2 normal-case tracking-normal">
                                  {hoveredAlertGroup.alerts.map((alertItem) => (
                                    <div key={alertItem.id} className={`border px-3 py-2 ${alertPopoverItemToneClass}`}>
                                      <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.16em] opacity-70">
                                        <span>{workspaceWindows.find((item) => item.id === alertItem.windowId)?.label || alertItem.windowId}</span>
                                        <span>{getAlertSeverityLabel(alertItem.severity)}</span>
                                      </div>
                                      <div className="mt-2 text-[10px] uppercase tracking-[0.16em] opacity-65">{alertItem.title}</div>
                                      <div className="mt-2 text-[11px] leading-5 opacity-90">{alertItem.message}</div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="mt-3 text-[11px] normal-case tracking-normal opacity-80">{tWork("alert_popover_empty")}</div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <div data-tour-target="workspace" className="min-h-0 flex-1 overflow-hidden p-4">
                      {activeWorkspaceContent}
                    </div>
                  </section>
                </div>

                {showTutorial && activeTutorialStep && (
                  <div className="fixed inset-0 z-[70]">
                    <div className="absolute inset-0 bg-black/78 backdrop-blur-[2px]" onClick={closeTutorial} />
                    {tutorialFocusStyle && (
                      <div
                        className="pointer-events-none absolute rounded-sm border-2 border-white shadow-[0_0_0_9999px_rgba(0,0,0,0.72),0_0_24px_rgba(255,255,255,0.25)]"
                        style={tutorialFocusStyle}
                      />
                    )}
                    <div
                      className="absolute border-2 border-foreground bg-background px-4 py-4 text-foreground shadow-[0_0_36px_rgba(255,255,255,0.18)]"
                      style={{
                        top: `${tutorialCardTop}px`,
                        left: `${tutorialCardLeft}px`,
                        width: `${tutorialCardWidth}px`,
                      }}
                    >
                      <div className="text-[10px] uppercase tracking-[0.18em] opacity-60">
                        {tWork("tour_step_label", { current: tutorialStepIndex + 1, total: tutorialSteps.length })}
                      </div>
                      <div className="mt-2 text-lg font-bold uppercase tracking-[0.12em]">{activeTutorialStep.title}</div>
                      <div className="mt-3 text-sm leading-7 opacity-85">{activeTutorialStep.body}</div>
                      <div className="mt-4 flex items-center justify-between gap-3 border-t border-foreground/20 pt-4 text-[10px] uppercase tracking-[0.16em]">
                        <button type="button" onClick={closeTutorial} className="border border-foreground/20 px-3 py-2 bg-foreground/5 hover:bg-foreground hover:text-background transition-none">
                          {tWork("tour_close")}
                        </button>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setTutorialStepIndex((current) => Math.max(current - 1, 0))}
                            disabled={tutorialStepIndex === 0}
                            className="border border-foreground/20 px-3 py-2 bg-foreground/5 hover:bg-foreground hover:text-background transition-none disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-foreground/5 disabled:hover:text-foreground"
                          >
                            {tWork("tour_prev")}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (tutorialStepIndex >= tutorialSteps.length - 1) {
                                closeTutorial();
                                return;
                              }
                              setTutorialStepIndex((current) => Math.min(current + 1, tutorialSteps.length - 1));
                            }}
                            className="border border-foreground px-3 py-2 bg-foreground text-background hover:bg-background hover:text-foreground transition-none"
                          >
                            {tutorialStepIndex >= tutorialSteps.length - 1 ? tWork("tour_finish") : tWork("tour_next")}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {pendingCriticalAction && (
                  <div
                    className="fixed inset-0 z-[80] flex items-center justify-center bg-black/80 px-4 py-6 backdrop-blur-sm"
                    onClick={() => {
                      if (!criticalActionBusy) {
                        setPendingCriticalAction(null);
                      }
                    }}
                  >
                    <div
                      role="dialog"
                      aria-modal="true"
                      className="w-full max-w-3xl border-2 border-foreground bg-background px-5 py-5 text-foreground shadow-[0_0_36px_rgba(255,255,255,0.18)] sm:px-6"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <div className="flex flex-col gap-3 border-b border-foreground/20 pb-4 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.22em] opacity-60">{tWork("critical_action_guard_label")}</div>
                          <div className="mt-2 text-lg font-bold uppercase tracking-[0.12em]">{criticalActionGuardTitle}</div>
                        </div>
                        <div className="border border-foreground/20 bg-foreground/5 px-3 py-1 text-[10px] uppercase tracking-[0.18em] opacity-80">
                          {pendingCriticalWindowLabel}
                        </div>
                      </div>

                      <div className="mt-4 text-sm leading-7 opacity-85">{criticalActionGuardBody}</div>
                      <div className="mt-4 border border-foreground/20 bg-foreground/5 px-4 py-3 text-xs leading-6 opacity-75">
                        {tWork("critical_action_guard_body")}
                      </div>

                      <div className="mt-5 text-[10px] uppercase tracking-[0.18em] opacity-65">
                        {tWork("critical_action_guard_alerts_label")}
                      </div>

                      {criticalAlertEntries.length > 0 ? (
                        <div className="mt-3 space-y-2">
                          {criticalAlertEntries.map((alertItem) => (
                            <button
                              key={alertItem.id}
                              onClick={() => setActiveWorkspaceWindow(alertItem.windowId)}
                              className="w-full border border-foreground/20 bg-foreground/5 px-4 py-3 text-left hover:bg-foreground/10"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-75">
                                <span>{workspaceWindows.find((item) => item.id === alertItem.windowId)?.label || alertItem.windowId}</span>
                                <span>{getAlertSeverityLabel(alertItem.severity)}</span>
                              </div>
                              <div className="mt-2 text-xs font-bold uppercase tracking-[0.14em]">{alertItem.title}</div>
                              <div className="mt-2 text-[11px] normal-case tracking-normal opacity-80">{alertItem.message}</div>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-3 border border-foreground/10 bg-black/20 px-4 py-3 text-xs leading-6 opacity-70">
                          {tWork("critical_action_guard_clear")}
                        </div>
                      )}

                      <div className="mt-6 flex flex-wrap justify-end gap-3">
                        <button
                          onClick={() => setPendingCriticalAction(null)}
                          disabled={criticalActionBusy}
                          className="border border-foreground/20 px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:bg-foreground/10 disabled:opacity-50"
                        >
                          {tWork("critical_action_guard_cancel")}
                        </button>
                        <button
                          onClick={() => {
                            void confirmCriticalActionGuard();
                          }}
                          disabled={criticalActionBusy}
                          className="bg-foreground px-4 py-2 text-[10px] font-bold uppercase tracking-[0.18em] text-background hover:opacity-85 disabled:opacity-50"
                        >
                          {criticalActionGuardConfirmLabel}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                {/*
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
                            const listedServerSessions = Array.isArray(session.listed_server_sessions) ? session.listed_server_sessions : [];
                            const loadedServerSessionId = String(session.loaded_server_session_id || "").trim();
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

                                      {loadedServerSessionId && (
                                        <div className="text-[10px] opacity-65 normal-case tracking-normal break-all">
                                          {tWork("local_acp_loaded_session")}: {loadedServerSessionId}
                                        </div>
                                      )}

                                      <div className="border border-foreground/10 bg-foreground/5 p-2 text-[10px] normal-case tracking-normal opacity-85 space-y-2">
                                        <div className="uppercase tracking-[0.14em] opacity-55">{tWork("local_acp_session_history_label")}</div>
                                        {listedServerSessions.length > 0 ? listedServerSessions.map((listedSession) => {
                                          const listedSessionSummary = acpListedSessionSummary(listedSession);
                                          const listActionKey = `load-session:${session.session_id}:${listedSession.sessionId}`;
                                          return (
                                            <div key={listedSession.sessionId} className="border border-foreground/10 bg-black/20 p-2 space-y-2">
                                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                                <div className="min-w-0">
                                                  <div className="truncate">{listedSession.title || listedSession.sessionId}</div>
                                                  <div className="mt-1 break-all opacity-65">{listedSession.sessionId}</div>
                                                </div>
                                                <button
                                                  className="border border-foreground/20 px-2 py-1 text-[10px] uppercase tracking-widest text-left hover:bg-foreground/10 disabled:opacity-50"
                                                  onClick={() => {
                                                    void handleLoadAcpServerSession(session, listedSession.sessionId);
                                                  }}
                                                  disabled={session.status !== "open" || localActionBusyKey === listActionKey}
                                                >
                                                  {loadedServerSessionId === listedSession.sessionId ? tWork("local_acp_session_loaded") : tWork("local_acp_session_load")}
                                                </button>
                                              </div>
                                              {listedSessionSummary && <div className="break-all opacity-65">{listedSessionSummary}</div>}
                                            </div>
                                          );
                                        }) : (
                                          <div className="opacity-65">{tWork("local_acp_session_history_empty")}</div>
                                        )}
                                      </div>

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
                                      void handleListAcpServerSessions(session);
                                    }}
                                    disabled={localActionBusyKey === `list-sessions:${session.session_id}` || session.status !== "open"}
                                  >
                                    {tWork("local_acp_session_list")}
                                  </button>
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
                    {renderAiSubsystemCards()}
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

                */}
      {/* Workflow Publish Dialog/Modal */}
      {showWorkflowModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="bg-background border-2 border-foreground p-6 max-w-xl w-full flex flex-col gap-6 shadow-[0_0_40px_rgba(var(--foreground-rgb),0.15)] animate-[fade-in_0.2s_ease-out]">
            <div className="flex justify-between items-center border-b-2 border-foreground pb-4">
              <h2 className="text-lg font-bold uppercase tracking-widest">{tWork("workflow_publish_title")}</h2>
              <button onClick={() => setShowWorkflowModal(false)} className="hover:bg-foreground hover:text-background px-2 py-1 font-bold transition-colors">
                ✕
              </button>
            </div>
            
            <div className="space-y-5">
               <div>
                  <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80 mb-2">
                     <span className="w-1.5 h-1.5 bg-foreground"></span>
                     {tWork("workflow_target")}
                  </label>
                  <select
                    className="w-full bg-foreground/5 border border-foreground/30 p-2.5 outline-none focus:border-foreground normal-case tracking-normal text-sm"
                    value={workflowModalTargetSelectValue}
                    onChange={(e) => handleWorkflowModalTargetSelection(e.target.value)}
                  >
                    <option value="">{tWork("workflow_target_generic")}</option>
                    {workflowTargetOptions.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                    <option value={WORKFLOW_TARGET_CUSTOM_VALUE}>{tWork("local_multimodal_kind_custom_option")}</option>
                  </select>
                  {showWorkflowModalCustomTargetInput && (
                    <input
                      type="text"
                      className="mt-2 w-full bg-foreground/5 border border-foreground/30 p-2.5 outline-none focus:border-foreground normal-case tracking-normal text-sm"
                      value={showWorkflowModalCustomTargetInput ? normalizedWorkflowModalKind : workflowModalCustomKind}
                      onChange={(e) => handleWorkflowModalCustomTargetChange(e.target.value)}
                      placeholder={tWork("local_multimodal_kind_custom_placeholder")}
                    />
                  )}
                  <div className="mt-2 text-[10px] normal-case tracking-normal opacity-65">
                    {tWork("local_multimodal_kind_help")}
                  </div>
                  {workflowModalSelectedService && (
                    <div className="mt-2 text-[10px] normal-case tracking-normal opacity-65 break-words">
                      {String(workflowModalSelectedService.description || workflowModalSelectedService.service_id || "")}
                    </div>
                  )}
               </div>
               
               <div>
                  <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80 mb-2">
                     <span className="w-1.5 h-1.5 bg-foreground"></span>
                     {tWork("workflow_prompt")}
                  </label>
                  <textarea 
                    className="w-full min-h-32 bg-foreground/5 border border-foreground/30 p-3 outline-none focus:border-foreground text-sm normal-case tracking-normal custom-scrollbar"
                    placeholder={tWork("workflow_prompt_placeholder")}
                    value={workflowModalPrompt}
                    onChange={(e) => setWorkflowModalPrompt(e.target.value)}
                  />
               </div>
               
               <div className="grid grid-cols-2 gap-4">
                  <div className="border border-foreground/20 p-3 space-y-2">
                     <div className="text-[10px] uppercase tracking-widest opacity-60 m-0">{tWork("local_multimodal_files")}: {workflowModalAttachments.length}</div>
                     <div className="text-[10px] normal-case tracking-normal opacity-60">
                       {tWork("local_multimodal_attachment_limit", {
                         count: MAX_MULTIMODAL_FILES,
                         sizeMb: String(MAX_MULTIMODAL_FILE_BYTES / (1024 * 1024)),
                       })}
                     </div>
                  </div>
                  <div className="flex flex-col justify-end gap-2">
                     <label className="cursor-pointer border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 text-center transition-colors">
                       {tWork("local_multimodal_add_files")}
                       <input type="file" multiple className="hidden" onChange={(e) => { void handleWorkflowModalFilesSelected(e); }} />
                     </label>
                     <button
                       className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50 transition-colors"
                       onClick={() => setWorkflowModalAttachments([])}
                       disabled={workflowModalAttachments.length === 0}
                     >
                       {tWork("local_multimodal_clear_files")}
                     </button>
                  </div>
               </div>

               {workflowPaymentState && (
                 <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                   <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("workflow_payment_title")}</div>
                   <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                     <div className="border border-foreground/10 bg-black/20 p-3 text-[10px] uppercase tracking-[0.14em] opacity-75">
                       <div className="opacity-55">{tWork("workflow_payment_challenge_id_label")}</div>
                       <div className="mt-1 normal-case tracking-normal opacity-100 break-all">{String(workflowPaymentState.payment?.challenge?.challenge_id || "-")}</div>
                     </div>
                     <div className="border border-foreground/10 bg-black/20 p-3 text-[10px] uppercase tracking-[0.14em] opacity-75">
                       <div className="opacity-55">{tWork("workflow_payment_recipient_label")}</div>
                       <div className="mt-1 normal-case tracking-normal opacity-100 break-all">{String(workflowPaymentState.payment?.challenge?.recipient || "-")}</div>
                     </div>
                     <div className="border border-foreground/10 bg-black/20 p-3 text-[10px] uppercase tracking-[0.14em] opacity-75">
                       <div className="opacity-55">{tWork("workflow_payment_amount_label")}</div>
                       <div className="mt-1 normal-case tracking-normal opacity-100 break-all">{String(workflowPaymentState.payment?.challenge?.amount_wei || "-")}</div>
                     </div>
                     <div className="border border-foreground/10 bg-black/20 p-3 text-[10px] uppercase tracking-[0.14em] opacity-75">
                       <div className="opacity-55">{tWork("workflow_payment_asset_label")}</div>
                       <div className="mt-1 normal-case tracking-normal opacity-100 break-all">{String(workflowPaymentState.payment?.challenge?.asset || "-")}</div>
                     </div>
                   </div>

                   <div className="border border-foreground/10 bg-black/20 p-3">
                     <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("workflow_payment_quote_label")}</div>
                     <pre className="mt-2 whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-85 m-0">{prettyDisplayJson(workflowPaymentState.payment?.quote || workflowPaymentState.quoteDetails || {})}</pre>
                   </div>

                   <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                     <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                       <span>{tWork("workflow_payment_payer")}</span>
                       <input
                         type="text"
                         className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                         value={workflowPaymentState.payer}
                         onChange={(e) => setWorkflowPaymentState((prev) => prev ? { ...prev, payer: e.target.value } : prev)}
                       />
                     </label>
                     <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                       <span>{tWork("workflow_payment_tx_hash")}</span>
                       <input
                         type="text"
                         className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                         value={workflowPaymentState.txHash}
                         onChange={(e) => setWorkflowPaymentState((prev) => prev ? { ...prev, txHash: e.target.value } : prev)}
                       />
                     </label>
                   </div>

                   <div className="flex flex-wrap gap-2">
                     <button
                       className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                       onClick={() => {
                         void issueWorkflowReceipt();
                       }}
                       disabled={workflowModalBusyAction !== "" || !workflowPaymentState.payer.trim() || !workflowPaymentState.txHash.trim()}
                     >
                       {tWork("workflow_receipt_issue")}
                     </button>
                     <button
                       className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                       onClick={() => {
                         void issueWorkflowRenterToken();
                       }}
                       disabled={workflowModalBusyAction !== "" || !workflowPaymentState.receipt}
                     >
                       {tWork("workflow_renter_token_issue")}
                     </button>
                   </div>

                   {workflowPaymentState.receipt && (
                     <div className="border border-foreground/10 bg-black/20 p-3">
                       <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("workflow_receipt_ready")}</div>
                       <pre className="mt-2 whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-85 m-0">{prettyDisplayJson(workflowPaymentState.receipt)}</pre>
                     </div>
                   )}

                   {workflowPaymentState.renterToken && (
                     <div className="border border-foreground/10 bg-black/20 p-3">
                       <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("workflow_renter_token_ready")}</div>
                       <pre className="mt-2 whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-85 m-0">{prettyDisplayJson(workflowPaymentState.renterToken)}</pre>
                     </div>
                   )}
                 </div>
               )}

               {workflowModalError && (
                 <div className="text-xs normal-case tracking-normal text-red-500 font-bold border border-red-500/20 bg-red-500/10 p-2">
                   {workflowModalError}
                 </div>
               )}
               {workflowModalNotice && (
                 <div className="text-xs normal-case tracking-normal border border-foreground/20 bg-foreground/5 p-2 opacity-80">
                   {workflowModalNotice}
                 </div>
               )}

               {workflowModalResult && (
                 <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-2">
                   <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("workflow_result_title")}</div>
                   <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{prettyDisplayJson(workflowModalResult)}</pre>
                 </div>
               )}
               
               <div className="pt-4 border-t border-foreground/20">
                 <button 
                   className="w-full bg-foreground text-background font-bold text-sm py-3.5 uppercase tracking-widest hover:opacity-85 hover:scale-[0.99] transition-all disabled:opacity-50 disabled:scale-100"
                   onClick={() => {
                      void executeWorkflowFromModal();
                   }}
                   disabled={workflowSubmitDisabled}
                 >
                   {workflowSubmitLabel}
                 </button>
               </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}




