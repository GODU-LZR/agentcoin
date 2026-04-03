"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations, useLocale } from "next-intl";
import { useTheme } from "next-themes";
import { useRouter, usePathname } from "next/navigation";

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

// ASCII Radar Scanner
const RADAR_AGENTS = [
  { name: 'GitHub Copilot', angle: Math.PI / 4, r: 6, x: 8, y: -4 },
  { name: 'Claude Code', angle: Math.PI * 3/4, r: 8, x: -11, y: -5 },
  { name: 'OpenAI Codex', angle: Math.PI * 5/4, r: 5, x: -7, y: 3 },
  { name: 'openclaw', angle: Math.PI * 7/4, r: 9, x: 12, y: 6 }
];

function renderRadarSweep(angle: number, foundIds: string[]): string {
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

  RADAR_AGENTS.forEach(agent => {
    if (foundIds.includes(agent.name)) {
      const ax = Math.round(CX + agent.x);
      const ay = Math.round(CY + agent.y);
      if (ax >= 0 && ax < W && ay >= 0 && ay < H) {
        buf[ay * W + ax] = '@';
        // Add a small label next to the dot
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
  const visionText = tWork('vision_text');

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
    setEarthDisplay(renderEarthSphere(earthAngleRef.current));
    setRadarDisplay(renderRadarSweep(radarAngleRef.current, []));
    setFoundAgents([]);
    setCheckedToJoin(agents.map(a => a.name)); // Default check existing agents

    const interval = setInterval(() => {
      // Keep earth updating in background as requested
      earthAngleRef.current += 0.09;
      setEarthDisplay(renderEarthSphere(earthAngleRef.current));

      // Radar scan logic
      radarAngleRef.current = (radarAngleRef.current + 0.15) % (2 * Math.PI);
      
      setFoundAgents(curr => {
         let newFound = [...curr];
         RADAR_AGENTS.forEach(a => {
            if (!newFound.includes(a.name)) {
               let diff = Math.abs(radarAngleRef.current - a.angle);
               if (diff > Math.PI) diff = 2 * Math.PI - diff;
               if (diff < 0.25) {
                 newFound.push(a.name);
               }
            }
         });
         setRadarDisplay(renderRadarSweep(radarAngleRef.current, newFound));
         return newFound;
      });
    }, 100);
    
    // Show scan complete state after 5.5 seconds
    const t = setTimeout(() => {
      setScanComplete(true);
    }, 5500);

    return () => {
      clearInterval(interval);
      clearTimeout(t);
    };
  }, [isDiscovering]);

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
      
      if (aliasesClear.includes(lowerCmd)) {
        setHistory([]);
      } else if (aliasesHelp.includes(lowerCmd)) {
        setHistory(prev => [...prev, { type: 'system', content: tCmd("help") }]);
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

  useEffect(() => {
    if (!showLanding) return;
    let frame = 0;
    const interval = setInterval(() => {
      earthAngleRef.current -= 0.05; // Spining slowly
      setEarthDisplay(renderEarthSphere(earthAngleRef.current));
      frame++;
      
      const charsToShow = Math.max(0, Math.floor((frame - 10) / 1.5));
      setTypedVision(visionText.substring(0, charsToShow));
      
      if (charsToShow >= visionText.length + 12) {
         setLandingStep(1);
      }
    }, 50);
    return () => clearInterval(interval);
  }, [showLanding, visionText]);

  if (!mounted) return null;

  if (showLanding) {
    return (
      <div className="min-h-screen bg-black text-white font-mono flex flex-col items-center justify-center overflow-x-hidden selection:bg-white selection:text-black relative w-full h-[100dvh]">
          {/* AgentCoin 覆盖于星球上半部 */}
          <div className="absolute top-[5%] md:top-[8%] w-full flex justify-center z-20 pointer-events-none drop-shadow-[0_0_25px_rgba(255,255,255,1)]" style={{textShadow: "0 0 10px rgba(255,255,255,0.9)"}}>
            <pre className="text-[12px] sm:text-[14px] md:text-[18px] font-bold text-center text-white mix-blend-screen scale-y-90 sm:scale-y-100">
              {ASCII_ART}
            </pre>
          </div>
          
          <div className="relative flex justify-center items-center w-full h-full mt-8 z-10 flex-grow">
            {/* 地球文本采用白色 + 发光特效 */}
            <pre className="text-[7.5px] sm:text-[9.5px] md:text-[11.5px] text-center text-white opacity-95 leading-[1.05] sm:leading-[1.1] m-0 pointer-events-none font-bold" style={{textShadow: "0 0 4px rgba(255,255,255,0.9)"}}>
              {earthDisplay || renderEarthSphere(0)}
            </pre>
            
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none mt-20 sm:mt-28 z-30">
              <div className="bg-black/85 backdrop-blur-sm p-4 sm:p-8 border-[1px] border-white max-w-3xl w-[min(92vw,960px)] text-center shadow-[0_0_40px_rgba(255,255,255,0.15)] animate-[fade-in_0.5s_ease-out] pointer-events-auto border-t-2 border-t-white">
                <pre className="text-white text-[10px] sm:text-[11px] md:text-xs whitespace-pre-wrap font-bold uppercase tracking-wide leading-[1.9] font-mono m-0 transition-all text-left inline-block" style={{ textShadow: "0 0 10px rgba(255,255,255,0.6)"}}>
                  {typedVision}
                  <span className="w-2.5 h-[1em] bg-white inline-block animate-pulse ml-1 align-bottom shadow-[0_0_12px_rgba(255,255,255,1)]"></span>
                </pre>
                
                {landingStep >= 1 && (
                   <div className="mt-8 flex justify-center">
                     <button 
                       onClick={() => setShowLanding(false)}
                       className="bg-white text-black px-6 py-3 uppercase tracking-widest text-[10px] sm:text-xs font-bold hover:bg-gray-300 transition-all border-2 border-transparent focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-4 focus:ring-offset-black hover:shadow-[0_0_20px_rgba(255,255,255,0.8)] active:translate-y-1 active:shadow-none"
                     >
                       {tWork("btn_enter_workspace", { defaultValue: "[ Initialize Workspace ]" })}
                     </button>
                   </div>
                )}
              </div>
            </div>
          </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground font-mono p-4 sm:p-6 selection:bg-foreground selection:text-background transition-colors duration-0 flex flex-col">
      
      {/* HEADER: Language & Theme Controls (Available Immediately) */}
      <header className="border-b-2 border-foreground pb-4 mb-6 flex justify-between items-end gap-4 flex-wrap shrink-0">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold uppercase tracking-wider">{tWork("title")}</h1>
          <p className="text-sm mt-3 flex items-center gap-2">
            <div className="transform scale-[0.4] origin-left mr-[-8px]"><AnatomicalHeart isOnline={isOnline} /></div>
            {isOnline ? tWork("status_online") : tWork("status_offline")}
          </p>
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
                  onClick={() => {
                     setIsAddingRemotePanel(true);
                     setIsDiscovering(false);
                  }}
                  className="hover:underline opacity-80 hover:opacity-100"
                >
                  {tWork("add_remote_agent")}
                </button>
                <button 
                  onClick={() => {
                     setIsDiscovering(true);
                     setIsAddingRemotePanel(false);
                  }}
                  disabled={isDiscovering}
                  className="hover:underline opacity-80 hover:opacity-100 disabled:opacity-50"
                >
                  {tWork("discover_agents")}
                </button>
              </div>
            </div>
            
            <div className="mt-2 text-sm flex-grow overflow-y-auto custom-scrollbar flex flex-col pr-1">
              <div className="p-4 text-left font-mono min-h-[220px] flex-grow relative flex flex-col">
                {isAddingRemotePanel ? (
                  <div className="flex flex-col w-full h-full animate-[fade-in_0.3s_ease-out]">
                    <div className="flex justify-center my-6">
                      <pre className="text-foreground font-bold tracking-widest text-xs sm:text-sm whitespace-pre">
                        {renderConnectAnimation()}
                      </pre>
                    </div>
                    
                    <div className="flex flex-col gap-4 mt-2">
                       <label className="flex flex-col gap-1 text-xs">
                          <span className="opacity-80">[{tWork("remote_endpoint")}]</span>
                          <input 
                             type="text"
                             className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors"
                             placeholder="agent-b.tailnet.internal:8080"
                             value={remoteForm.endpoint}
                             onChange={e => setRemoteForm({...remoteForm, endpoint: e.target.value})}
                          />
                       </label>
                       <label className="flex flex-col gap-1 text-xs">
                          <span className="opacity-80">[{tWork("remote_peer_id")}]</span>
                          <input 
                             type="text"
                             className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors"
                             placeholder="agentcoin-peer-b"
                             value={remoteForm.peerId}
                             onChange={e => setRemoteForm({...remoteForm, peerId: e.target.value})}
                          />
                       </label>
                       <label className="flex flex-col gap-1 text-xs">
                          <span className="opacity-80">[{tWork("remote_name")}]</span>
                          <input 
                             type="text"
                             className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors"
                             placeholder="AgentCoin Peer B"
                             value={remoteForm.name}
                             onChange={e => setRemoteForm({...remoteForm, name: e.target.value})}
                          />
                       </label>

                       <div className="flex justify-end gap-4 mt-6">
                          <button 
                            className="hover:underline opacity-70 hover:opacity-100"
                            onClick={() => {
                               setIsAddingRemotePanel(false);
                               setTimeout(() => inputRef.current?.focus(), 50);
                            }}
                          >
                            {tWork("btn_cancel")}
                          </button>
                          <button 
                            className="bg-foreground text-background font-bold px-4 py-1 hover:opacity-80 transition-opacity"
                            onClick={() => {
                               setIsAddingRemotePanel(false);
                               setHistory(prev => [
                                 ...prev,
                                 { type: 'system', content: `Creating secure peer connection via Headscale...` },
                                 { type: 'system', content: `Registered new remote node: ${remoteForm.name || 'Unknown'}` }
                               ]);
                               setRemoteForm({endpoint: '', peerId: '', name: ''});
                               setTimeout(() => inputRef.current?.focus(), 50);
                            }}
                          >
                            {tWork("btn_connect")}
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
                         ? tWork("radar_complete", { found: foundAgents.length, total: 4 })
                         : tWork("radar_scanning", { found: foundAgents.length, total: 4 })}
                    </div>
                    <div className="w-full space-y-3 flex-grow">
                      {agents.filter(a => foundAgents.includes(a.name)).map((agent, idx) => (
                        <div key={idx} className="flex justify-between items-center bg-foreground/10 p-3 px-4 border border-foreground/20 rounded-sm animate-[fade-in_0.3s_ease-out] shadow-sm">
                          <div className="flex items-center gap-4">
                            <div className="transform scale-[0.6] origin-left w-[36px] h-[36px] flex items-center justify-center">
                              {agent.icon}
                            </div>
                            <span className="text-sm font-bold">{agent.name}</span>
                          </div>
                          <div className="flex flex-col items-end gap-1.5">
                            <span className="text-[10px] text-green-500 font-bold bg-green-500/10 px-2 py-0.5 rounded">{tWork("radar_found")}</span>
                            <label className="flex items-center gap-1.5 cursor-pointer group/chk">
                              <span className="text-[9px] sm:text-[10px] opacity-70 group-hover/chk:opacity-100 uppercase tracking-widest">{tWork("radar_join_network")}</span>
                              <div className={`w-3 h-3 sm:w-4 sm:h-4 border-2 ${checkedToJoin.includes(agent.name) ? 'bg-foreground border-foreground' : 'border-foreground/50'} flex items-center justify-center transition-colors`}>
                                {checkedToJoin.includes(agent.name) && <span className="text-background text-[10px] leading-none font-bold">✓</span>}
                              </div>
                              <input 
                                type="checkbox" 
                                className="hidden"
                                checked={checkedToJoin.includes(agent.name)}
                                onChange={e => {
                                  if (e.target.checked) setCheckedToJoin(prev => [...prev, agent.name]);
                                  else setCheckedToJoin(prev => prev.filter(n => n !== agent.name));
                                }}
                              />
                            </label>
                          </div>
                        </div>
                      ))}
                    </div>
                    
                    <div className="flex justify-end gap-4 mt-6 w-full shrink-0 border-t border-foreground/10 pt-4">
                       {scanComplete && (
                         <button 
                           className="hover:underline opacity-80 hover:opacity-100 text-xs mr-auto transition-opacity"
                           onClick={() => {
                              setIsDiscovering(false);
                              setTimeout(() => setIsDiscovering(true), 10);
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
                         className="bg-foreground text-background font-bold px-4 py-1 hover:opacity-80 transition-opacity text-xs"
                         onClick={() => {
                            setIsDiscovering(false);
                            setHistory(prev => [
                              ...prev,
                              { type: 'system', content: `[Network] ${checkedToJoin.length} local agents synchronized to cluster.` }
                            ]);
                            setTimeout(() => inputRef.current?.focus(), 50);
                         }}
                       >
                         {tWork("btn_confirm_join")}
                       </button>
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
            
            <div className="mt-8 text-xs text-muted-foreground border-t border-foreground/30 pt-4 shrink-0">
              <p>{tWork("clear_hint_prefix")}<span className="text-foreground font-bold">clear</span>{tWork("clear_hint_suffix")}</p>
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}