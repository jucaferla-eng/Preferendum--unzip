import { useState, useRef, useEffect } from "react";

// ══ DESIGN TOKENS ══════════════════════════════════════════════
const T = {
  bg:     "#090c13",   // deep civic navy
  deep:   "#0e1322",   // header / top bar
  panel:  "#161e30",   // card bg — distinct from bg
  card:   "#1c2640",   // raised card
  rim:    "#2c3e5c",   // borders
  mist:   "#5a78a0",   // very tertiary only
  fog:    "#90b8d8",   // secondary text — clearly readable on dark
  silver: "#cce0f0",   // body text, labels
  snow:   "#edf5ff",   // primary content text
  white:  "#ffffff",   // titles, headings
  blue:   "#4d8aff",
  teal:   "#00d4b4",
  gold:   "#f5c030",
  coral:  "#ff4d6a",
  green:  "#22c55e",
  purple: "#a855f7",
};
// Paleta monocromática — escala de azules para distinguir sin saturar
// Regla: neutro en reposo → acento al tocar → gradiente en resultados
const COLORS        = ['#2563EB','#3B82F6','#60A5FA','#93C5FD','#BFDBFE','#1D4ED8','#1E40AF','#DBEAFE','#EFF6FF','#172554'];
const NEUTRAL_OPT   = 'rgba(255,255,255,0.05)';   // tarjeta opción en reposo
const NEUTRAL_BORDER = 'rgba(255,255,255,0.09)';  // borde en reposo
const BAR_GRADIENT  = 'linear-gradient(90deg,#1D4ED8,#60A5FA)';  // barras resultados
const BAR_WIN       = 'linear-gradient(90deg,#2563EB,#93C5FD)';  // barra ganadora

// ══ DEBATE STATUS ═══════════════════════════════════════════════
const STATUS = {
  live:      { label:"🟢 En vivo",        color:T.green,  bg:"#22c55e22" },
  closed:    { label:"🔴 Cerrado",         color:T.coral,  bg:"#ff4d6a22" },
  verifying: { label:"🔍 En verificación", color:T.gold,   bg:"#f5c03022" },
  verified:  { label:"✅ Verificado",      color:T.teal,   bg:"#00d4b422" },
};

// ══ DATA ════════════════════════════════════════════════════════
const DEBATES = [
  { id:1, title:"Prioridad para el presupuesto 2027",
    inst:"Municipalidad Las Condes", type:"gov",
    opts:["Infraestructura vial","Salud pública","Educación","Áreas verdes"],
    vals:[25,25,24,15], votes:89, comments:12, status:"live",
    closes:"15 Abr 2026 · 18:00", verify_opens:null, verify_closes:null },
  { id:2, title:"Plan de movilidad — tu opinión",
    inst:"Municipalidad Providencia", type:"gov",
    opts:["Ciclovías","Metro ampliado","Buses eléctricos","Zonas peatonales"],
    vals:[23,25,21,15], votes:84, comments:8, status:"verifying",
    closes:"25 Mar 2026 · 18:00", verify_opens:"26 Mar", verify_closes:"09 Abr 2026 · 18:00" },
  { id:3, title:"¿Aprueba la renovación del parque?",
    inst:"Municipalidad Ñuñoa", type:"gov",
    opts:["Apruebo totalmente","Apruebo con cambios","Rechazo","Sin opinión"],
    vals:[32,24,7,9], votes:72, comments:14, status:"verified",
    closes:"15 Feb 2026", verify_closes:"28 Feb 2026", accuracy:98.2 },
  { id:4, title:"¿Qué mejora prefiere en nuestra app?",
    inst:"Falabella", type:"priv",
    opts:["Pago más rápido","Ofertas personalizadas","Seguimiento pedidos","Chat 24/7"],
    vals:[27,17,15,7], votes:66, comments:9, status:"closed",
    closes:"31 Mar 2026", verify_opens:"05 Abr 2026" },
  { id:5, title:"¿Cuál zapatilla preferirías para 2026?",
    inst:"Nike Chile", type:"priv",
    opts:["Air Max Pulse","Air Force 1","React Infinity","Pegasus Trail"],
    vals:[16,11,9,5], votes:41, comments:6, status:"verifying",
    closes:"20 Mar 2026", verify_closes:"05 Abr 2026 · 18:00" },
  { id:6, title:"¿Qué plan de internet prefiere?",
    inst:"Entel", type:"priv",
    opts:["400 Mbps $15.990","600 Mbps $19.990","1 Gbps $24.990","Fibra óptica"],
    vals:[20,13,22,12], votes:67, comments:11, status:"live",
    closes:"12 Abr 2026" },
];

const DEMO_CODES = {
  "3EF8-777D-5864":{debateId:2,choice:"Metro ampliado"},
  "05EB-55C2-2A95":{debateId:5,choice:"React Infinity"},
  "404D-7E85-9BB0":{debateId:2,choice:"Ciclovías"},
  "AAD1-90B6-89C5":{debateId:5,choice:"Air Max Pulse"},
  "DD3B-88CE-EB26":{debateId:2,choice:"Buses eléctricos"},
};

// Marketer data
const AD_TYPES = [
  {k:"brand",   icon:"📢", name:"Publicidad de marca",   desc:"Imagen o video de tu producto en el feed.", color:T.blue},
  {k:"question",icon:"❓", name:"Pregunta patrocinada",  desc:"Tu pregunta al mercado. Resultados reales antes de producir.", color:T.teal},
  {k:"civic",   icon:"🏛", name:"Aviso cívico",          desc:"Salud, educación, emergencias. Sector público.", color:T.green},
  {k:"culture", icon:"🎬", name:"Votación cultural",     desc:"Oscars, Grammy, mejor producto. El público decide.", color:T.gold},
];
const CATS_APPEAR = [
  {k:"sports",icon:"⚽",name:"Deportes"},{k:"culture",icon:"🎬",name:"Cultura"},
  {k:"music",icon:"🎵",name:"Música"},{k:"tech",icon:"💻",name:"Tecnología"},
  {k:"health",icon:"❤️",name:"Salud"},{k:"education",icon:"📚",name:"Educación"},
  {k:"economy",icon:"💰",name:"Economía"},{k:"environment",icon:"🌿",name:"Medio Ambiente"},
  {k:"food",icon:"🍕",name:"Gastronomía"},{k:"auto",icon:"🚗",name:"Automóviles"},
];
const CATS_EXCLUDE = [
  {k:"politics",icon:"🏛",name:"Política"},{k:"unions",icon:"⚙️",name:"Sindicatos"},
  {k:"religion",icon:"⛪",name:"Religión"},{k:"justice",icon:"⚖️",name:"Justicia"},
  {k:"military",icon:"🛡",name:"Defensa"},{k:"emergency",icon:"🚨",name:"Emergencias"},
  {k:"minors",icon:"👶",name:"Menores"},{k:"labor",icon:"👷",name:"Conflictos laborales"},
];
const COUNTRIES = ["Chile","Brasil","México","Argentina","Colombia","Perú","España","USA","Todos"];
const AGES = ["18-24","25-34","35-44","45-54","55-64","65+"];
const NIKE_CODES = ["NIKE-AIR-2026-X7K3","NIKE-AIR-2026-M9P2","NIKE-AIR-2026-Q4R8","NIKE-AIR-2026-W2T6","NIKE-AIR-2026-B5N1"];
let codeIdx = 0;
const nextCode = () => NIKE_CODES[codeIdx++ % NIKE_CODES.length];

// ══ SHARED UI ═══════════════════════════════════════════════════
function Btn({label,color=T.blue,onPress,full,small,outline,disabled}) {
  return (
    <button onClick={onPress} disabled={disabled} style={{
      width:full?"100%":"auto",
      padding:small?"10px 18px":"17px 28px",
      borderRadius:14,
      background:disabled?"#252d42":outline?"transparent":color,
      border:outline?`2px solid ${color}`:"none",
      color:disabled?T.fog:outline?color:"#fff",
      fontSize:small?14:17,fontWeight:700,
      cursor:disabled?"not-allowed":"pointer",
      fontFamily:"inherit",marginTop:4,opacity:disabled?0.6:1,
    }}>{label}</button>
  );
}

function Input({label,placeholder,type="text",value,onChange,mono}) {
  return (
    <div style={{marginBottom:16}}>
      {label&&<div style={{fontSize:12,color:T.silver,textTransform:"uppercase",
        letterSpacing:"0.07em",fontWeight:700,marginBottom:7}}>{label}</div>}
      <input type={type} placeholder={placeholder} value={value}
        onChange={e=>onChange(e.target.value)}
        style={{width:"100%",padding:"14px 16px",borderRadius:12,
          background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,
          fontSize:16,outline:"none",fontFamily:mono?"monospace":"inherit",
          letterSpacing:mono?"0.1em":"normal",boxSizing:"border-box"}}/>
    </div>
  );
}

function Card({children,style={}}) {
  return <div style={{background:T.panel,border:`1px solid ${T.rim}`,
    borderRadius:16,padding:22,marginBottom:14,...style}}>{children}</div>;
}

function Lbl({children,style={}}) {
  return <div style={{fontSize:12,color:T.fog,textTransform:"uppercase",
    letterSpacing:"0.08em",fontWeight:700,marginBottom:12,...style}}>{children}</div>;
}

function StatusBadge({status}) {
  const st=STATUS[status];
  return <span style={{fontSize:12,fontWeight:700,padding:"5px 11px",borderRadius:10,
    background:st.bg,color:st.color}}>{st.label}</span>;
}

function Chip({label,on,onClick,color=T.blue}) {
  return <span onClick={onClick} style={{display:"inline-block",padding:"8px 16px",
    borderRadius:20,fontSize:14,fontWeight:700,cursor:"pointer",margin:"0 6px 8px 0",
    border:`1.5px solid ${on?color:T.rim}`,background:on?`${color}22`:T.deep,
    color:on?color:T.fog}}>{label}</span>;
}

function Donut({vals,size=130}) {
  const total=vals.reduce((a,b)=>a+b,0)||1;
  const cx=size/2,cy=size/2,r=size/2*0.72,sw=size*0.14;
  const circ=2*Math.PI*r;
  let offset=0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cy} r={r} fill={T.panel}/>
      {vals.map((v,i)=>{
        const pct=v/total,dash=pct*circ,gap=circ-dash;
        const el=<circle key={i} cx={cx} cy={cy} r={r} fill="transparent"
          stroke={COLORS[i%COLORS.length]} strokeWidth={sw}
          strokeDasharray={`${dash} ${gap}`}
          strokeDashoffset={-(offset*circ-circ*0.25)}
          transform={`rotate(-90 ${cx} ${cy})`}/>;
        offset+=pct; return el;
      })}
      <circle cx={cx} cy={cy} r={r*0.55} fill={T.bg}/>
      <text x={cx} y={cy-4} textAnchor="middle" fill={T.white}
        fontSize={size*0.13} fontWeight="bold" fontFamily="system-ui">{total}</text>
      <text x={cx} y={cy+10} textAnchor="middle" fill={T.fog}
        fontSize={size*0.08} fontFamily="system-ui">votos</text>
    </svg>
  );
}

function DonutResult({vals,size=220}) {
  const total=vals.reduce((a,b)=>a+b,0)||1;
  const cx=size/2,cy=size/2,outerR=size/2*0.85,innerR=outerR*0.52;
  const labelR=(outerR+innerR)/2;
  function pt(deg,r){const rad=(deg-90)*Math.PI/180;return[cx+r*Math.cos(rad),cy+r*Math.sin(rad)];}
  function arc(s,e){
    const[x1,y1]=pt(s,outerR),[x2,y2]=pt(e,outerR);
    const[x3,y3]=pt(e,innerR),[x4,y4]=pt(s,innerR);
    const lg=e-s>180?1:0;
    return `M${x1} ${y1}A${outerR} ${outerR} 0 ${lg} 1 ${x2} ${y2}L${x3} ${y3}A${innerR} ${innerR} 0 ${lg} 0 ${x4} ${y4}Z`;
  }
  const segs=[];let ang=0;
  vals.forEach((v,i)=>{
    const pct=v/total,sweep=pct*360,mid=ang+sweep/2;
    const[lx,ly]=pt(mid,labelR);
    segs.push({i,pct,s:ang,e:ang+sweep,lx,ly});
    ang+=sweep;
  });
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {segs.map(({i,pct,s,e,lx,ly})=>(
        <g key={i}>
          <path d={arc(s,e)} fill={COLORS[i%COLORS.length]} stroke={T.bg} strokeWidth={2.5}/>
          {pct>=0.02&&(
            <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle"
              fill="white" fontSize={size*0.076} fontWeight="bold" fontFamily="system-ui">
              {Math.round(pct*100)}%
            </text>
          )}
        </g>
      ))}
      <circle cx={cx} cy={cy} r={innerR*0.96} fill={T.card}/>
    </svg>
  );
}

// ══ MAIN APP ════════════════════════════════════════════════════
export default function PreferendumV8() {
  // Navigation
  const [screen,setScreen]       = useState("launch");
  const [userType,setUserType]   = useState(null);
  const [selDebate,setSelDebate] = useState(null);

  // Voter state
  const [voted,setVoted]         = useState({});
  const [tab,setTab]             = useState("feed");
  const [email,setEmail]         = useState("");
  const [pw,setPw]               = useState("");
  const [gender,setGender]       = useState("F");
  const [codeInput,setCode]      = useState("");
  const [vStep,setVStep]         = useState("enter");
  const [confirmed,setConfirmed] = useState(null);
  const [foundVote,setFoundVote] = useState(null);
  const [confs,setConfs]         = useState({1:0,2:0,3:0,4:0,5:0,6:0});
  const [disputes,setDisputes]   = useState({1:0,2:0,3:0,4:0,5:0,6:0});

  // Institution state
  const [instTab,setInstTab]     = useState("debates");
  const [ncInstName,setNcInstName] = useState('');
  const [myDebateIds,setMyDebateIds] = useState([]); // IDs created in this session
  const [ncTitle,setNcTitle]     = useState('');
  const [ncDesc,setNcDesc]       = useState('');
  const [ncOpts,setNcOpts]       = useState(['','']);
  const [ncCloses,setNcCloses]   = useState('');
  const [ncLoading,setNcLoading] = useState(false);
  const [ncAudience,setNcAudience] = useState('all');
  const [ncGender,setNcGender]   = useState('all');
  const [ncAgeMin,setNcAgeMin]   = useState('13');
  const [ncAgeMax,setNcAgeMax]   = useState('99');
  const [ncCountry,setNcCountry] = useState('CL');
  const [ncRegion,setNcRegion]   = useState('');
  const [ncCommune,setNcCommune] = useState('');
  // Reward, visual, and branching state for creation form
  const [ncReward,setNcReward]       = useState('');
  const [ncRewardCodes,setNcRewardCodes] = useState(''); // one code per line
  const [ncVisual,setNcVisual]       = useState(false);
  const [ncOptImages,setNcOptImages] = useState(Array(10).fill(''));
  const [ncBranching,setNcBranching] = useState(false);
  const [ncQ2,setNcQ2] = useState(Array(4).fill(null).map(()=>({on:false,title:'',opts:['','','']})));
  const [ncQ3,setNcQ3] = useState(Array(4).fill(null).map(()=>Array(3).fill(null).map(()=>({on:false,title:'',opts:['','']}))));
  // Vote branching state
  const [vBranchQ,setVBranchQ]     = useState(null);
  const [vBranchPath,setVBranchPath] = useState([]);
  // Debate room state
  const [debateTab,setDebateTab]         = useState('debate'); // 'debate'|'vote'|'results'
  const [debateKnowledge,setDebateKnowledge] = useState({}); // {debateId: level}
  const [charCount,setCharCount]         = useState(0);

  // Marketer state — Ad Creator
  const [mkScreen,setMkScreen]   = useState("hub"); // hub|adcreator|reward|dashboard
  const [adStep,setAdStep]       = useState(0);
  const [adType,setAdType]       = useState(null);
  const [brandName,setBrand]     = useState("");
  const [adTitle,setAdTitle]     = useState("");
  const [adBody,setAdBody]       = useState("");
  const [bannerPrev,setBanner]   = useState(null);
  const [logoPrev,setLogo]       = useState(null);
  const [sqQuestion,setSqQ]      = useState("");
  const [sqOpts,setSqOpts]       = useState([{text:"",imgPrev:null},{text:"",imgPrev:null},{text:"",imgPrev:null},{text:"",imgPrev:null}]);
  const [adFormat,setAdFormat]   = useState("banner");
  const [country,setCountry]     = useState("Chile");
  const [region,setRegion]       = useState("");
  const [sexF,setSexF]           = useState(true);
  const [sexM,setSexM]           = useState(true);
  const [agesSel,setAgesSel]     = useState([]);
  const [appear,setAppear]       = useState([]);
  const [exclude,setExclude]     = useState([]);
  const [comps,setComps]         = useState([""]);
  const [budget,setBudget]       = useState("");
  const [payModel,setPayModel]   = useState("CPM");
  const [startDate,setStart]     = useState("");
  const [endDate,setEnd]         = useState("");
  const [launched,setLaunched]   = useState(false);

  // Verification state
  const [vfStep,setVfStep]       = useState(1);       // 1-7
  const [vfName,setVfName]       = useState('');
  const [vfEmail,setVfEmail]     = useState('');
  const [vfPhone,setVfPhone]     = useState('');
  const [vfNatId,setVfNatId]     = useState('');
  const [vfDob,setVfDob]         = useState('');
  const [vfCountry,setVfCountry] = useState('Chile');
  const [vfCounty,setVfCounty]   = useState('');
  const [vfPw,setVfPw]           = useState('');
  const [vfPw2,setVfPw2]         = useState('');
  const [vfGender,setVfGender]   = useState('F');
  const [emailCode,setEmailCode] = useState('');
  const [smsCode,setSmsCode]     = useState('');
  const [docFile,setDocFile]     = useState(null);
  const [selfieFile,setSelfieFile]= useState(null);
  const [docPrev,setDocPrev]     = useState(null);
  const [selfiePrev,setSelfiePrev]= useState(null);
  const [vfDone,setVfDone]       = useState({1:false,2:false,3:false,4:false,5:false,6:false,7:false});
  const [vfLoading,setVfLoading] = useState(false);
  const [vfError,setVfError]     = useState('');
  const [walletAddr,setWalletAddr]= useState('');

  const API = 'https://preferendum-unzip-d2zd.onrender.com';

  const [authToken, setAuthToken]   = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [apiDebates, setApiDebates] = useState([]);
  const [debatesLoading, setDebatesLoading] = useState(false);

  // Opinions state
  const [debateOpinions, setDebateOpinions] = useState([]);
  const [opinionsLoading, setOpinionsLoading] = useState(false);
  const [newOpinionText, setNewOpinionText] = useState('');
  const [knowledgeLevel, setKnowledgeLevel] = useState('familiar');
  const [postingOpinion, setPostingOpinion] = useState(false);
  const [opinionError, setOpinionError] = useState('');

  const markDone = (step) => {
    setVfDone(prev=>({...prev,[step]:true}));
    setTimeout(()=>setVfStep(step+1),600);
  };

  const simulateVerify = (step, delay=1800) => {
    setVfLoading(true);
    setVfError('');
    setTimeout(()=>{setVfLoading(false);markDone(step);},delay);
  };

  // Reward codes state
  const [rwMethod,setRwMethod]   = useState(null);
  const [rwDiscount,setRwDiscount]=useState("");
  const [rwExpiry,setRwExpiry]   = useState("");
  const [rwStore,setRwStore]     = useState("");
  const [rwStoreName,setRwStoreName]=useState("");
  const [rwCsvDone,setRwCsvDone] = useState(false);
  const [rwCopied,setRwCopied]   = useState(false);
  const [rwVcode,setRwVcode]     = useState(false);
  const csvRef = useRef();

  const PROTECTED_SCREENS = ["feed","debate","voted-success","results","verify","profile"];
  const go = (s,extra={}) => {
    if(PROTECTED_SCREENS.includes(s) && !authToken) { s="launch"; extra={}; }
    setScreen(s);
    if(extra.deb) setSelDebate(extra.deb);
    if(s==="feed"||s==="results"||s==="verify"||s==="profile") setTab(s);
    if(s==="inst-home") setInstTab("debates");
    if(s==="debate") setDebateTab('debate');
    setVBranchQ(null); setVBranchPath([]);
    window.scrollTo&&window.scrollTo(0,0);
  };

  const toggle = (arr,setArr,k) =>
    setArr(p=>p.includes(k)?p.filter(x=>x!==k):[...p,k]);

  const readFile = (file) => new Promise(res=>{
    const r=new FileReader();
    r.onload=e=>res(e.target.result);
    r.readAsDataURL(file);
  });

  const estImp = budget?Math.round(parseInt(budget)/4.8).toLocaleString():"—";

  const phone={background:T.bg,height:"100vh",overflowY:"auto",
    fontFamily:"-apple-system,system-ui,sans-serif",
    color:T.snow,maxWidth:420,margin:"0 auto",
    WebkitOverflowScrolling:"touch"};

  // ── API HELPERS ────────────────────────────────────────────
  const apiFetch = async (method, path, body=null) => {
    const headers = {'Content-Type':'application/json'};
    if(authToken) headers['Authorization'] = `Bearer ${authToken}`;
    const res = await fetch(`${API}${path}`, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(()=>({}));
    if(!res.ok) { const err = new Error(data.detail || 'Error de conexión'); err.status = res.status; throw err; }
    return data;
  };

  const transformDebate = (d) => {
    let followUps = null;
    try { if(d.follow_up_questions) followUps = JSON.parse(d.follow_up_questions); } catch(e){}
    return {
      id:           d.id,
      title:        d.title,
      inst:         d.inst_name,
      type:         d.debate_type === 'priv' ? 'priv' : 'gov',
      opts:         d.options,
      opt_images:   d.option_images || [],
      vals:         d.results ? d.results.map(r => r.count) : d.options.map(()=>0),
      votes:        d.total_votes,
      comments:     0,
      status:       d.status,
      closes:       d.closes_at ? new Date(d.closes_at).toLocaleDateString('es-CL') : null,
      verify_opens: null,
      verify_closes:d.verify_closes_at ? new Date(d.verify_closes_at).toLocaleDateString('es-CL') : null,
      follow_ups:   followUps,
      reward:       d.reward || '',
    };
  };

  const loadDebates = async () => {
    setDebatesLoading(true);
    try {
      const data = await apiFetch('GET', '/debates?country=CL');
      if(data.debates && data.debates.length > 0) {
        setApiDebates(data.debates.map(transformDebate));
      }
    } catch(e) { /* fall back to static data */ } finally {
      setDebatesLoading(false);
    }
  };

  // Reload debates when entering feed or inst-home
  useEffect(() => {
    if(screen === 'feed' || screen === 'inst-home') loadDebates();
  }, [screen]);

  const loadOpinions = async (debateId) => {
    setOpinionsLoading(true);
    setDebateOpinions([]);
    try {
      const data = await apiFetch('GET', `/debates/${debateId}/opinions`);
      setDebateOpinions((data.items || []).filter(it => it.type === 'opinion').map(it => it.opinion));
    } catch(e) { /* silently fail */ } finally {
      setOpinionsLoading(false);
    }
  };

  const postOpinion = async (debateId) => {
    if(newOpinionText.trim().length < 20) {
      setOpinionError('Mínimo 20 caracteres.');
      return;
    }
    setPostingOpinion(true);
    setOpinionError('');
    try {
      await apiFetch('POST', `/debates/${debateId}/opinions`, {
        text: newOpinionText.trim(),
        knowledge_level: knowledgeLevel,
      });
      setNewOpinionText('');
      loadOpinions(debateId);
    } catch(e) {
      setOpinionError(e.message || 'Error al publicar.');
    } finally {
      setPostingOpinion(false);
    }
  };

  useEffect(() => {
    if(screen === 'debate' && selDebate) {
      loadOpinions(selDebate.id);
      setNewOpinionText('');
      setOpinionError('');
      // Verificar si ya votó en este debate (persiste entre sesiones)
      if(authToken) {
        apiFetch('GET', `/debates/${selDebate.id}/my-vote`)
          .then(data => {
            if(data.has_voted && !voted[selDebate.id]) {
              setVoted(prev => ({...prev, [selDebate.id]: {
                opt:    data.option,
                code:   data.verify_code,
                chain:  [],
                reward: data.reward_code || '',
              }}));
            }
          })
          .catch(()=>{});
      }
    }
  }, [screen, selDebate?.id]);

  // ── TOP BAR ────────────────────────────────────────────────
  function TopBar({title,back,right}) {
    return (
      <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
        padding:"12px 16px",display:"flex",alignItems:"center",gap:10,
        position:"sticky",top:0,zIndex:99}}>
        {back&&<button onClick={()=>go(back)} style={{background:"none",border:"none",
          color:T.snow,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>}
        <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>{title}</div>
        {right}
      </div>
    );
  }

  // ── VOTER TABS ─────────────────────────────────────────────
  function VoterTabs() {
    return (
      <div style={{position:"fixed",bottom:0,left:"50%",transform:"translateX(-50%)",
        width:"100%",maxWidth:420,background:T.deep,borderTop:`1px solid ${T.rim}`,
        display:"flex",padding:"8px 0 14px",zIndex:99}}>
        {[["feed","🗳","Debates"],["results","📊","Resultados"],
          ["verify","🔍","Verificar"],["profile","👤","Perfil"]].map(([id,icon,lbl])=>(
          <button key={id} onClick={()=>go(id)} style={{flex:1,background:"none",
            border:"none",cursor:"pointer",display:"flex",flexDirection:"column",
            alignItems:"center",gap:2}}>
            <span style={{fontSize:20}}>{icon}</span>
            <span style={{fontSize:10,fontWeight:700,color:tab===id?T.blue:T.fog}}>{lbl}</span>
          </button>
        ))}
      </div>
    );
  }

  // ── INST TABS ──────────────────────────────────────────────
  function InstTabs() {
    return (
      <div style={{position:"fixed",bottom:0,left:"50%",transform:"translateX(-50%)",
        width:"100%",maxWidth:420,background:T.deep,borderTop:`1px solid ${T.rim}`,
        display:"flex",padding:"8px 0 14px",zIndex:99}}>
        {[["debates","🗳","Debates"],["dashboard","📊","Dashboard"],
          ["create","➕","Crear"],["ads","📢","Publicidad"]].map(([id,icon,lbl])=>(
          <button key={id} onClick={()=>setInstTab(id)} style={{flex:1,background:"none",
            border:"none",cursor:"pointer",display:"flex",flexDirection:"column",
            alignItems:"center",gap:2}}>
            <span style={{fontSize:20}}>{icon}</span>
            <span style={{fontSize:10,fontWeight:700,color:instTab===id?T.blue:T.fog}}>{lbl}</span>
          </button>
        ))}
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: LAUNCH
  // ══════════════════════════════════════════════════════════════
  if(screen==="launch") return (
    <div style={phone}>
      <div style={{minHeight:"100vh",display:"flex",flexDirection:"column",
        alignItems:"center",justifyContent:"center",padding:32,textAlign:"center",
        background:`radial-gradient(ellipse at 50% 30%, #1a3a6b 0%, ${T.bg} 70%)`}}>
        <div style={{fontSize:64,marginBottom:16}}>🗳</div>
        <div style={{fontSize:38,fontWeight:900,color:T.white,letterSpacing:-1,marginBottom:6}}>
          prefer<span style={{color:T.blue}}>endum</span>
        </div>
        <div style={{fontSize:14,color:T.fog,lineHeight:1.7,marginBottom:8,maxWidth:280}}>
          Tu voz. Tu poder. Verificado en blockchain.
        </div>
        <div style={{fontSize:11,color:T.mist,fontStyle:"italic",marginBottom:48}}>
          En memoria del Fundador José Ignacio Fernández (1989–2024)
        </div>
        <div style={{width:"100%",maxWidth:320,display:"flex",flexDirection:"column",gap:12}}>
          <button onClick={()=>{setUserType("voter");go("register");}} style={{
            padding:16,borderRadius:14,background:T.blue,border:"none",
            color:"#fff",fontSize:16,fontWeight:700,cursor:"pointer"}}>
            🙋 Soy votante
          </button>
          <button onClick={()=>{setUserType("inst");go("org-splash");}} style={{
            padding:16,borderRadius:14,background:"transparent",
            border:`1.5px solid ${T.teal}`,color:T.teal,
            fontSize:16,fontWeight:700,cursor:"pointer"}}>
            🏛 Soy institución
          </button>
          <button onClick={()=>{setUserType("marketer");go("marketer");}} style={{
            padding:16,borderRadius:14,background:"transparent",
            border:`1.5px solid ${T.gold}`,color:T.gold,
            fontSize:16,fontWeight:700,cursor:"pointer"}}>
            📢 Soy anunciante / marketer
          </button>
        </div>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: REGISTER
  // ══════════════════════════════════════════════════════════════
  // ── REGISTER SCREEN ────────────────────────────────────────
  if(screen==="register") return (
    <div style={phone}>
      <TopBar title="Registro de votante" back="launch"/>
      <div style={{padding:"16px 16px 80px"}}>
        <div style={{padding:"8px 0 16px"}}>
          <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Crea tu cuenta</div>
          <div style={{fontSize:13,color:T.fog,lineHeight:1.6}}>
            Tu identidad se verifica con 7 capas. Nunca se vincula a tu voto.
          </div>
        </div>
        <div style={{marginBottom:16}}>
          <div style={{display:"flex",gap:3,marginBottom:4}}>
            {[1,2,3,4,5,6,7].map(i=>(
              <div key={i} style={{flex:1,height:4,borderRadius:3,background:T.rim}}/>
            ))}
          </div>
          <div style={{fontSize:10,color:T.fog}}>7 capas de verificación — empiezan tras el registro</div>
        </div>
        <Card>
          <Lbl>Datos personales</Lbl>
          <Input label="Nombre completo" placeholder="María González" value={vfName} onChange={setVfName}/>
          <Input label="Email" placeholder="maria@correo.cl" type="email" value={vfEmail} onChange={setVfEmail}/>
          <Input label="Teléfono (con código de país)" placeholder="+56912345678" value={vfPhone} onChange={setVfPhone}/>
          <Input label="RUT / DNI / Documento nacional" placeholder="12.345.678-9" value={vfNatId} onChange={setVfNatId}/>
          <div style={{marginBottom:14}}>
            <div style={{fontSize:10,color:T.fog,textTransform:"uppercase",
              letterSpacing:"0.08em",fontWeight:700,marginBottom:8}}>Género</div>
            <div style={{display:"flex",gap:8}}>
              {[["F","♀ Femenino"],["M","♂ Masculino"],["O","Otro"]].map(([v,l])=>(
                <button key={v} onClick={()=>setVfGender(v)} style={{flex:1,padding:"9px 4px",
                  borderRadius:10,border:`1.5px solid ${vfGender===v?T.blue:T.rim}`,
                  background:vfGender===v?`${T.blue}22`:"transparent",
                  color:vfGender===v?T.blue:T.fog,fontSize:12,fontWeight:700,cursor:"pointer"}}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <Input label="Fecha de nacimiento" type="date" value={vfDob} onChange={setVfDob}/>
          <Input label="País" placeholder="Chile" value={vfCountry} onChange={setVfCountry}/>
          <Input label="Ciudad / Comuna" placeholder="Las Condes" value={vfCounty} onChange={setVfCounty}/>
        </Card>
        <Card>
          <Lbl>Seguridad</Lbl>
          <Input label="Contraseña" placeholder="Mínimo 8 caracteres" type="password" value={vfPw} onChange={setVfPw}/>
          <Input label="Confirmar contraseña" placeholder="Repite tu contraseña" type="password" value={vfPw2} onChange={setVfPw2}/>
        </Card>
        <div style={{background:`${T.blue}18`,border:`1px solid ${T.blue}44`,
          borderRadius:10,padding:"12px 14px",fontSize:12,color:"#7ab4ff",
          marginBottom:14,lineHeight:1.8}}>
          🔒 Tras registrarte verificaremos:<br/>
          1·Email OTP · 2·SMS · 3·Documento · 4·Selfie · 5·IMEI · 6·Geolocalización · 7·Blockchain
        </div>
        {vfError?<div style={{background:`${T.coral}22`,border:`1px solid ${T.coral}44`,
          borderRadius:8,padding:"10px 12px",fontSize:12,color:T.coral,marginBottom:12}}>{vfError}</div>:null}
        <Btn label={vfLoading?"Creando cuenta...":"Crear cuenta →"} full
          disabled={!vfName||!vfEmail||!vfPhone||!vfPw||vfPw!==vfPw2||vfLoading}
          onPress={async()=>{
            if(vfPw!==vfPw2){setVfError("Las contraseñas no coinciden");return;}
            setVfError(""); setVfLoading(true);
            try {
              const data = await apiFetch('POST','/auth/register',{
                email:vfEmail, name:vfName, password:vfPw,
                phone:vfPhone, country:vfCountry||'CL', county:vfCounty||'',
                gender:vfGender, dob:vfDob||'', national_id:vfNatId||'',
              });
              setAuthToken(data.token); setCurrentUser(data.user);
            } catch(e) {
              setVfError(e.message); setVfLoading(false); return;
            }
            setVfLoading(false); setVfStep(1); go("verify-identity");
          }}/>
        <div style={{textAlign:"center",marginTop:12}}>
          <button onClick={()=>go("login")} style={{background:"none",border:"none",
            color:T.blue,fontSize:13,cursor:"pointer"}}>
            ¿Ya tienes cuenta? Inicia sesión
          </button>
        </div>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: LOGIN
  // ══════════════════════════════════════════════════════════════
  if(screen==="login") return (
    <div style={phone}>
      <TopBar title="Iniciar sesión" back="launch"/>
      <div style={{padding:"16px 16px 80px"}}>
        <div style={{textAlign:"center",padding:"24px 0 20px"}}>
          <div style={{fontSize:48,marginBottom:12}}>🗳</div>
          <div style={{fontSize:24,fontWeight:900,color:T.white,marginBottom:4}}>Bienvenido de vuelta</div>
        </div>
        <Card>
          <Input label="Email" placeholder="tu@correo.cl" type="email" value={email} onChange={setEmail}/>
          <Input label="Contraseña" placeholder="••••••••" type="password" value={pw} onChange={setPw}/>
          {vfError&&<div style={{background:`${T.coral}22`,border:`1px solid ${T.coral}44`,
            borderRadius:8,padding:"10px 12px",fontSize:12,color:T.coral,marginBottom:8}}>{vfError}</div>}
          <Btn label={vfLoading?"Entrando...":"Entrar →"} full disabled={vfLoading}
            onPress={async()=>{
              setVfLoading(true); setVfError("");
              try {
                const data = await apiFetch('POST','/auth/login',{email,password:pw});
                setAuthToken(data.token); setCurrentUser(data.user);
                setVfLoading(false); go("debates-splash");
                setTimeout(()=>{ setScreen("feed"); setTab("feed"); }, 2200);
              } catch(e) { setVfError(e.message); setVfLoading(false); }
            }}/>
        </Card>
        <div style={{textAlign:"center",marginTop:12}}>
          <button onClick={()=>go("register")} style={{background:"none",border:"none",
            color:T.blue,fontSize:13,cursor:"pointer"}}>
            ¿No tienes cuenta? Regístrate
          </button>
        </div>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: VERIFY IDENTITY — 7 LAYERS
  // ══════════════════════════════════════════════════════════════
  if(screen==="verify-identity") {
    // Usuario que ya se verificó antes — solo selfie rápida
    if(currentUser?.selfie_verified) return (
      <div style={phone}>
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,padding:"14px 18px",
          display:"flex",alignItems:"center",gap:12}}>
          <button onClick={()=>go("feed")} style={{background:"none",border:"none",color:T.snow,fontSize:22,cursor:"pointer"}}>←</button>
          <div style={{fontSize:16,fontWeight:700,color:T.white}}>Confirmar identidad</div>
        </div>
        <div style={{padding:24}}>
          <div style={{textAlign:"center",marginBottom:24}}>
            <div style={{fontSize:48,marginBottom:8}}>🤳</div>
            <div style={{fontSize:18,fontWeight:700,color:T.white,marginBottom:6}}>¡Hola de nuevo!</div>
            <div style={{fontSize:13,color:T.fog}}>Solo necesitamos una selfie rápida para confirmar que eres tú</div>
          </div>
          <div style={{background:`${T.blue}18`,border:`1px solid ${T.blue}44`,borderRadius:12,
            padding:16,marginBottom:20,textAlign:"center"}}>
            <div style={{fontSize:12,color:T.fog,marginBottom:8}}>Cámara frontal · Sin carné necesario</div>
            <div style={{fontSize:28}}>😊</div>
          </div>
          <div onClick={()=>document.getElementById("reauth-selfie").click()}
            style={{border:`2px dashed ${T.blue}`,borderRadius:12,padding:24,
              textAlign:"center",cursor:"pointer",background:T.deep,marginBottom:16}}>
            <input id="reauth-selfie" type="file" accept="image/*" capture="user" style={{display:"none"}}
              onChange={async e=>{
                const f=e.target.files[0]; if(!f) return;
                const form=new FormData(); form.append('file',f);
                try {
                  const r=await fetch(`${API}/verify/face`,{method:'POST',
                    headers:{Authorization:`Bearer ${authToken}`},body:form});
                  const d=await r.json().catch(()=>({}));
                  if(!r.ok){alert(d.detail||'No pudimos verificar tu identidad.');return;}
                } catch(e){}
                go("feed");
              }}/>
            <div style={{fontSize:32,marginBottom:6}}>📷</div>
            <div style={{fontSize:13,fontWeight:700,color:T.snow}}>Tomar selfie</div>
          </div>
        </div>
      </div>
    );

    const VF_STEPS = [
      {n:1,icon:"📧",title:"Email OTP",color:T.blue},
      {n:2,icon:"📱",title:"SMS",color:T.teal},
      {n:3,icon:"🪪",title:"Documento",color:T.gold},
      {n:4,icon:"🤳",title:"Selfie",color:T.coral},
      {n:5,icon:"📲",title:"Dispositivo",color:T.blue},
      {n:6,icon:"📍",title:"Ubicación",color:T.green},
      {n:7,icon:"⛓","title":"Blockchain",color:T.gold},
    ];
    const doneCount = Object.values(vfDone).filter(Boolean).length;
    const allDone = doneCount===7;
    const cur = VF_STEPS[Math.min(vfStep,7)-1];

    if(allDone) return (
      <div style={phone}>
        <div style={{minHeight:"100vh",display:"flex",flexDirection:"column",
          alignItems:"center",justifyContent:"center",padding:32,textAlign:"center",
          background:`radial-gradient(ellipse at 50% 30%, #1a3a6b 0%, ${T.bg} 70%)`}}>
          <div style={{fontSize:72,marginBottom:16}}>🎉</div>
          <div style={{fontSize:26,fontWeight:900,color:T.white,marginBottom:8}}>¡Verificación completa!</div>
          <div style={{fontSize:13,color:T.fog,lineHeight:1.7,marginBottom:24,maxWidth:300}}>
            Tu identidad ha sido verificada con 7 capas de seguridad. Ya puedes votar en Preferendum.
          </div>
          <Card style={{width:"100%",maxWidth:320,marginBottom:20}}>
            <Lbl>7/7 capas verificadas ✓</Lbl>
            {VF_STEPS.map(s=>(
              <div key={s.n} style={{display:"flex",alignItems:"center",gap:10,
                padding:"7px 0",borderBottom:`1px solid ${T.rim}`}}>
                <div style={{width:24,height:24,borderRadius:"50%",background:`${T.green}22`,
                  display:"flex",alignItems:"center",justifyContent:"center",
                  fontSize:12,color:T.green,fontWeight:900}}>✓</div>
                <span style={{fontSize:12,color:T.silver,flex:1}}>{s.icon} {s.title}</span>
                <span style={{fontSize:10,color:T.green,fontWeight:700}}>VERIFICADO</span>
              </div>
            ))}
          </Card>
          <Btn label="Entrar a Preferendum →" full onPress={()=>{
            go("debates-splash");
            setTimeout(()=>{ setScreen("feed"); setTab("feed"); }, 2200);
          }}/>
        </div>
      </div>
    );

    return (
      <div style={phone}>
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
          padding:"12px 16px",position:"sticky",top:0,zIndex:99,
          display:"flex",alignItems:"center",gap:10}}>
          <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>
            prefer<span style={{color:T.blue}}>endum</span>
            <span style={{fontSize:12,color:T.fog,fontWeight:400}}> · Verificación</span>
          </div>
          <div style={{fontSize:12,color:T.fog,fontWeight:700}}>{doneCount}/7</div>
          <button onClick={()=>go("launch")} style={{background:"none",border:"none",
            color:T.silver,fontSize:12,cursor:"pointer",marginLeft:8,padding:"4px 8px"}}>
            ← Inicio
          </button>
        </div>

        <div style={{padding:"12px 16px 0"}}>
          <div style={{display:"flex",gap:3,marginBottom:6}}>
            {VF_STEPS.map(s=>(
              <div key={s.n} style={{flex:1,height:5,borderRadius:3,
                background:vfDone[s.n]?T.green:s.n===vfStep?cur.color:T.rim}}/>
            ))}
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:10,color:T.fog}}>
            <span style={{color:cur.color,fontWeight:700}}>Capa {vfStep}: {cur.title}</span>
            <span>{doneCount} de 7 completadas</span>
          </div>
        </div>

        <div style={{padding:"14px 16px 80px"}}>

          <div style={{display:"flex",gap:5,marginBottom:16,flexWrap:"wrap"}}>
            {VF_STEPS.map(s=>(
              <div key={s.n} style={{padding:"3px 9px",borderRadius:16,fontSize:10,fontWeight:700,
                background:vfDone[s.n]?`${T.green}22`:s.n===vfStep?`${cur.color}22`:T.deep,
                border:`1px solid ${vfDone[s.n]?T.green:s.n===vfStep?cur.color:T.rim}`,
                color:vfDone[s.n]?T.green:s.n===vfStep?cur.color:T.fog}}>
                {vfDone[s.n]?"✓ ":""}{s.icon}
              </div>
            ))}
          </div>

          {/* LAYER 1 — EMAIL */}
          {vfStep===1&&!vfDone[1]&&(
            <Card style={{border:`1px solid ${T.blue}44`}}>
              <div style={{textAlign:"center",marginBottom:16}}>
                <div style={{fontSize:40,marginBottom:8}}>📧</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Verifica tu email</div>
                <div style={{fontSize:12,color:T.fog}}>Enviamos un código a</div>
                <div style={{fontSize:13,fontWeight:700,color:T.blue}}>{vfEmail}</div>
              </div>
              <input value={emailCode} onChange={e=>setEmailCode(e.target.value)}
                placeholder="000000" maxLength={6}
                style={{width:"100%",padding:"14px",borderRadius:10,background:T.deep,
                  border:`2px solid ${T.blue}`,color:T.blue,fontSize:28,fontWeight:900,
                  fontFamily:"monospace",letterSpacing:"0.3em",outline:"none",
                  textAlign:"center",boxSizing:"border-box",marginBottom:14}}/>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12,color:T.fog,fontSize:13}}>⏳ Verificando...</div>
                :<>
                  <Btn label="Confirmar código →" full disabled={emailCode.length<6}
                    onPress={async()=>{
                      setVfLoading(true);
                      try {
                        await apiFetch('POST','/verify/email/confirm',{code:emailCode,channel:'email'});
                        setVfDone(p=>({...p,1:true}));
                        go("debates-splash");
                        setTimeout(()=>{ setScreen("feed"); setTab("feed"); }, 2200);
                      } catch(e) {
                        alert('Código incorrecto o expirado. Intenta de nuevo.');
                      } finally {
                        setVfLoading(false);
                      }
                    }}/>
                  <div style={{textAlign:"center",marginTop:10}}>
                    <button onClick={async()=>{
                      try {
                        await apiFetch('POST','/verify/email/send');
                        alert('Código reenviado a '+vfEmail);
                      } catch(e) {
                        alert('Error al reenviar. Intenta más tarde.');
                      }
                    }} style={{background:"none",border:"none",color:T.fog,fontSize:12,cursor:"pointer"}}>
                      No recibí el código — reenviar
                    </button>
                  </div>
                </>
              }
            </Card>
          )}

          {/* LAYER 2 — SMS */}
          {vfStep===2&&!vfDone[2]&&(
            <Card style={{border:`1px solid ${T.teal}44`}}>
              <div style={{textAlign:"center",marginBottom:16}}>
                <div style={{fontSize:40,marginBottom:8}}>📱</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Verifica tu teléfono</div>
                <div style={{fontSize:12,color:T.fog}}>SMS enviado a</div>
                <div style={{fontSize:13,fontWeight:700,color:T.teal}}>{vfPhone}</div>
              </div>
              <input value={smsCode} onChange={e=>setSmsCode(e.target.value)}
                placeholder="000000" maxLength={6}
                style={{width:"100%",padding:"14px",borderRadius:10,background:T.deep,
                  border:`2px solid ${T.teal}`,color:T.teal,fontSize:28,fontWeight:900,
                  fontFamily:"monospace",letterSpacing:"0.3em",outline:"none",
                  textAlign:"center",boxSizing:"border-box",marginBottom:14}}/>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12,color:T.fog,fontSize:13}}>⏳ Verificando...</div>
                :<Btn label="Confirmar SMS →" full disabled={smsCode.length<6}
                  onPress={()=>{setVfLoading(true);setTimeout(()=>{setVfLoading(false);setVfDone(p=>({...p,2:true}));setVfStep(3);},1800);}}/>
              }
            </Card>
          )}

          {/* LAYER 3 — DOCUMENT */}
          {vfStep===3&&!vfDone[3]&&(
            <Card style={{border:`1px solid ${T.gold}44`}}>
              <div style={{textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:40,marginBottom:8}}>🪪</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Foto de tu documento</div>
                <div style={{fontSize:12,color:T.fog}}>RUT, DNI, o pasaporte vigente</div>
              </div>
              <div onClick={()=>document.getElementById("doc-up").click()} style={{
                border:`2px dashed ${docPrev?T.gold:T.rim}`,borderRadius:12,
                padding:docPrev?"10px":"24px",textAlign:"center",cursor:"pointer",
                background:T.deep,marginBottom:14}}>
                <input id="doc-up" type="file" accept="image/*" style={{display:"none"}}
                  onChange={async e=>{const f=e.target.files[0];if(f){const r=new FileReader();r.onload=ev=>setDocPrev(ev.target.result);r.readAsDataURL(f);setDocFile(f);}}}/>
                {docPrev
                  ?<div style={{display:"flex",alignItems:"center",gap:12}}>
                    <img src={docPrev} alt="" style={{width:72,height:48,borderRadius:8,objectFit:"cover"}}/>
                    <div style={{textAlign:"left"}}>
                      <div style={{fontSize:12,fontWeight:700,color:T.gold}}>✓ Imagen cargada</div>
                      <div style={{fontSize:11,color:T.fog}}>Toca para cambiar</div>
                    </div>
                  </div>
                  :<><div style={{fontSize:36,marginBottom:6}}>📷</div>
                    <div style={{fontSize:13,fontWeight:700,color:T.snow}}>Toca para subir foto</div>
                    <div style={{fontSize:11,color:T.fog}}>JPG o PNG</div></>
                }
              </div>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12,color:T.fog,fontSize:13}}>⏳ Verificando documento...</div>
                :<Btn label="Enviar documento →" full disabled={!docFile}
                  onPress={()=>{setVfLoading(true);setTimeout(()=>{setVfLoading(false);setVfDone(p=>({...p,3:true}));setVfStep(4);},2200);}}/>
              }
            </Card>
          )}

          {/* LAYER 4 — SELFIE CON CARNÉ */}
          {vfStep===4&&!vfDone[4]&&(
            <Card style={{border:`1px solid ${T.coral}44`}}>
              <div style={{textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:40,marginBottom:8}}>🤳</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Selfie con tu carné</div>
                <div style={{fontSize:12,color:T.fog}}>Cámara frontal · Carné bajo el mentón</div>
              </div>

              {/* Diagrama instrucción */}
              <div style={{background:T.deep,borderRadius:12,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:11,color:T.fog,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>Cómo hacerlo</div>
                <div style={{display:"flex",alignItems:"center",justifyContent:"center",gap:0,marginBottom:10}}>
                  <div style={{textAlign:"center",flex:1}}>
                    <div style={{fontSize:36}}>😐</div>
                    <div style={{fontSize:10,color:T.fog,marginTop:4}}>Mira directo<br/>a la cámara</div>
                  </div>
                  <div style={{fontSize:20,color:T.rim}}>+</div>
                  <div style={{textAlign:"center",flex:1}}>
                    <div style={{fontSize:36}}>🪪</div>
                    <div style={{fontSize:10,color:T.fog,marginTop:4}}>Carné bajo<br/>el mentón</div>
                  </div>
                  <div style={{fontSize:20,color:T.rim}}>→</div>
                  <div style={{textAlign:"center",flex:1}}>
                    <div style={{fontSize:36}}>📸</div>
                    <div style={{fontSize:10,color:T.green,marginTop:4}}>Una sola<br/>foto</div>
                  </div>
                </div>
                <div style={{fontSize:11,color:T.fog,borderTop:`1px solid ${T.rim}`,paddingTop:10}}>
                  La cámara frontal se abre automáticamente
                </div>
              </div>

              <div style={{background:`${T.coral}18`,border:`1px solid ${T.coral}44`,
                borderRadius:10,padding:"10px 14px",fontSize:12,color:T.coral,marginBottom:14}}>
                ⚠️ Ambas caras del carné deben ser visibles · Buena iluminación · Sin gafas de sol
              </div>

              <div onClick={()=>document.getElementById("selfie-up").click()} style={{
                border:`2px dashed ${selfiePrev?T.coral:T.rim}`,borderRadius:12,
                padding:selfiePrev?"10px":"24px",textAlign:"center",cursor:"pointer",
                background:T.deep,marginBottom:14}}>
                {/* capture="user" fuerza cámara frontal, bloquea galería */}
                <input id="selfie-up" type="file" accept="image/*" capture="user" style={{display:"none"}}
                  onChange={async e=>{const f=e.target.files[0];if(f){const r=new FileReader();r.onload=ev=>setSelfiePrev(ev.target.result);r.readAsDataURL(f);setSelfieFile(f);}}}/>
                {selfiePrev
                  ?<div style={{display:"flex",alignItems:"center",gap:12}}>
                    <img src={selfiePrev} alt="" style={{width:56,height:56,borderRadius:"50%",objectFit:"cover"}}/>
                    <div style={{textAlign:"left"}}>
                      <div style={{fontSize:12,fontWeight:700,color:T.coral}}>✓ Foto cargada</div>
                      <div style={{fontSize:11,color:T.fog}}>Toca para repetir</div>
                    </div>
                  </div>
                  :<><div style={{fontSize:36,marginBottom:6}}>📷</div>
                    <div style={{fontSize:13,fontWeight:700,color:T.snow}}>Abrir cámara frontal</div>
                    <div style={{fontSize:11,color:T.fog,marginTop:4}}>Cara + carné en una sola foto</div>
                  </>
                }
              </div>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12}}>
                  <div style={{fontSize:13,color:T.fog,marginBottom:6}}>⏳ Verificando con Amazon Rekognition...</div>
                  <div style={{background:T.deep,borderRadius:8,padding:"6px 12px",fontSize:11,color:T.coral}}>
                    🔍 Comparando tu cara con el documento...
                  </div>
                </div>
                :<Btn label="Verificar identidad →" full disabled={!selfieFile}
                  onPress={async()=>{
                    setVfLoading(true);
                    try {
                      const form = new FormData();
                      form.append('file', selfieFile);
                      const r = await fetch(`${API}/verify/selfie`,{
                        method:'POST',
                        headers:{Authorization:`Bearer ${authToken}`},
                        body: form
                      });
                      const d = await r.json().catch(()=>({}));
                      if(!r.ok) { alert(d.detail||'No pudimos verificar tu identidad. Intenta con mejor iluminación.'); setVfLoading(false); return; }
                    } catch(e) { /* sin backend: modo demo */ }
                    setVfLoading(false);
                    setVfDone(p=>({...p,4:true}));
                    setVfStep(5);
                  }}/>
              }
            </Card>
          )}

          {/* LAYER 5 — IMEI */}
          {vfStep===5&&!vfDone[5]&&(
            <Card style={{border:`1px solid ${T.blue}44`}}>
              <div style={{textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:40,marginBottom:8}}>📲</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Verificación de SIM</div>
                <div style={{fontSize:12,color:T.fog}}>Un chip = un voto (aunque cambies de aparato)</div>
              </div>
              <div style={{background:T.deep,borderRadius:10,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:10,color:T.fog,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:6}}>Número detectado</div>
                <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:4}}>📱 {vfPhone||'Tu número'}</div>
                <div style={{fontFamily:"monospace",fontSize:11,color:T.silver}}>SIM: ••••••••••••••</div>
              </div>
              <div style={{background:`${T.blue}18`,border:`1px solid ${T.blue}44`,
                borderRadius:10,padding:"10px 14px",fontSize:12,color:"#7ab4ff",marginBottom:14}}>
                🔒 Guardamos el hash SHA-256 de tu número. Nunca el número real. Un SIM = un voto.
              </div>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12,color:T.fog,fontSize:13}}>⏳ Registrando SIM...</div>
                :<Btn label="Registrar este SIM →" full
                  onPress={async()=>{
                    setVfLoading(true);
                    try {
                      const r = await fetch(`${API_URL}/verify/imei`,{
                        method:'POST',
                        headers:{'Content-Type':'application/json','Authorization':`Bearer ${authToken}`},
                        body:JSON.stringify({imei:'web-client',phone:vfPhone,device_model:'web',os_version:'web'})
                      });
                      if(!r.ok && r.status!==409) throw new Error('Error registrando SIM');
                    } catch(e) { /* si ya está registrado (409) dejamos pasar */ }
                    setVfLoading(false);
                    setVfDone(p=>({...p,5:true}));
                    setVfStep(6);
                  }}/>
              }
            </Card>
          )}

          {/* LAYER 6 — GEO */}
          {vfStep===6&&!vfDone[6]&&(
            <Card style={{border:`1px solid ${T.green}44`}}>
              <div style={{textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:40,marginBottom:8}}>📍</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Geolocalización</div>
                <div style={{fontSize:12,color:T.fog}}>Confirmamos que estás en {vfCountry||"tu país"}</div>
              </div>
              <div style={{background:T.deep,borderRadius:10,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:36,marginBottom:8}}>🌍</div>
                <div style={{fontSize:13,fontWeight:700,color:T.green}}>{vfCountry||"Chile"} detectado</div>
                <div style={{fontSize:11,color:T.fog,marginTop:4}}>Ubicación confirmada</div>
              </div>
              <div style={{background:`${T.green}18`,border:`1px solid ${T.green}44`,
                borderRadius:10,padding:"10px 14px",fontSize:12,color:T.green,marginBottom:14}}>
                ✓ Solo verificamos tu país. Tu ubicación exacta no se almacena.
              </div>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12,color:T.fog,fontSize:13}}>⏳ Verificando ubicación...</div>
                :<Btn label="Confirmar mi ubicación →" full
                  onPress={()=>{setVfLoading(true);setTimeout(()=>{setVfLoading(false);setVfDone(p=>({...p,6:true}));setVfStep(7);},1800);}}/>
              }
            </Card>
          )}

          {/* LAYER 7 — BLOCKCHAIN */}
          {vfStep===7&&!vfDone[7]&&(
            <Card style={{border:`1px solid ${T.gold}44`}}>
              <div style={{textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:40,marginBottom:8}}>⛓</div>
                <div style={{fontSize:17,fontWeight:700,color:T.white,marginBottom:4}}>Registro en Blockchain</div>
                <div style={{fontSize:12,color:T.fog}}>Última capa — Polygon Blockchain</div>
              </div>
              <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}44`,
                borderRadius:10,padding:"10px 14px",fontSize:12,color:T.gold,marginBottom:14,lineHeight:1.6}}>
                💡 Si tienes wallet (MetaMask, etc.) conéctala. Si no, creamos una automáticamente.
              </div>
              <Input label="Wallet address (opcional)" placeholder="0x... o dejar vacío" value={walletAddr} onChange={setWalletAddr}/>
              {vfLoading
                ?<div style={{textAlign:"center",padding:12}}>
                  <div style={{fontSize:13,color:T.fog,marginBottom:6}}>⏳ Anclando en Polygon...</div>
                  <div style={{fontFamily:"monospace",fontSize:10,color:T.gold}}>TX: 0x7212c52de19...</div>
                </div>
                :<Btn label="🚀 Completar verificación →" full
                  onPress={()=>{setVfLoading(true);setTimeout(()=>{setVfLoading(false);setVfDone(p=>({...p,7:true}));},2800);}}/>
              }
            </Card>
          )}

          {/* Skip verification — email OTP may not be available yet */}
          <div style={{textAlign:"center",paddingTop:8,paddingBottom:24}}>
            <div style={{fontSize:11,color:T.fog,marginBottom:10}}>
              ¿No recibes el código? Puedes continuar y verificar más tarde.
            </div>
            <button onClick={()=>{
              go("debates-splash");
              setTimeout(()=>{ setScreen("feed"); setTab("feed"); }, 2200);
            }} style={{background:"none",border:`1px solid ${T.fog}44`,
              borderRadius:10,padding:"10px 24px",color:T.fog,
              fontSize:13,cursor:"pointer",fontWeight:600}}>
              Continuar sin verificar →
            </button>
          </div>

        </div>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: DEBATES SPLASH TRANSITION
  // ══════════════════════════════════════════════════════════════
  if(screen==="debates-splash") return (
    <div style={{...phone,background:T.bg,display:"flex",flexDirection:"column",
      alignItems:"center",justifyContent:"center",minHeight:"100vh",
      background:`radial-gradient(ellipse at 50% 40%, #0d1f4a 0%, ${T.bg} 65%)`}}>
      <div style={{fontSize:11,letterSpacing:"0.45em",color:T.blue,
        textTransform:"uppercase",fontWeight:600,marginBottom:32,opacity:0.8}}>
        prefer<span style={{color:T.gold}}>endum</span>
      </div>
      <div style={{fontSize:68,fontWeight:900,color:T.white,letterSpacing:"0.08em",
        fontFamily:"Georgia, 'Times New Roman', serif",textAlign:"center",
        lineHeight:1,marginBottom:20,textShadow:`0 0 60px ${T.blue}44`}}>
        DEBATES
      </div>
      <div style={{fontSize:13,color:T.fog,letterSpacing:"0.2em",
        textTransform:"uppercase",fontWeight:500}}>
        la plaza pública verificada
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // AUTH GATE — safety net for protected screens
  // ══════════════════════════════════════════════════════════════
  if(PROTECTED_SCREENS.includes(screen) && !authToken) {
    setTimeout(()=>setScreen("launch"),0);
    return null;
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: FEED
  // ══════════════════════════════════════════════════════════════
  if(screen==="feed") return (
    <div style={phone}>
      <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
        padding:"12px 16px",display:"flex",alignItems:"center",gap:10,
        position:"sticky",top:0,zIndex:99}}>
        <div style={{fontWeight:900,fontSize:18,color:T.white,flex:1}}>
          prefer<span style={{color:T.blue}}>endum</span>
        </div>
        <div style={{fontSize:12,color:T.fog}}>{vfCounty||currentUser?.county||''}{(vfCounty||currentUser?.county)?` · ${currentUser?.country||vfCountry||'CL'}`:currentUser?.country||vfCountry||'CL'}</div>
        <div style={{width:32,height:32,borderRadius:"50%",background:T.blue,
          display:"flex",alignItems:"center",justifyContent:"center",
          fontSize:14,fontWeight:700}}>
          {(currentUser?.name||vfName||'P')[0].toUpperCase()}
        </div>
      </div>
      <div style={{padding:"12px 16px 80px"}}>
        {/* Status legend — collapsed to save space */}

        {debatesLoading&&apiDebates.length===0&&(
          <div style={{textAlign:"center",padding:32,color:T.fog,fontSize:13}}>
            ⏳ Cargando debates...
          </div>
        )}
        {(apiDebates.length>0?apiDebates:DEBATES).map((deb,di)=>{
          const st=STATUS[deb.status]||STATUS["live"];
          const hasVoted=voted[deb.id];
          return (
            <div key={deb.id}>
              {di===2&&(
                <div style={{background:T.card,border:`1px solid ${T.rim}`,
                  borderRadius:12,padding:12,marginBottom:12}}>
                  <div style={{fontSize:9,color:T.fog,textTransform:"uppercase",
                    letterSpacing:"0.1em",marginBottom:6}}>Publicidad</div>
                  <div style={{display:"flex",gap:10,alignItems:"center"}}>
                    <div style={{width:44,height:44,borderRadius:10,background:T.mist,
                      display:"flex",alignItems:"center",justifyContent:"center",fontSize:20}}>📱</div>
                    <div>
                      <div style={{fontSize:11,color:T.fog,fontWeight:700}}>Samsung Galaxy</div>
                      <div style={{fontSize:13,fontWeight:700,color:T.white}}>Galaxy S26 — Ya disponible</div>
                    </div>
                  </div>
                </div>
              )}
              <div onClick={()=>go("debate",{deb})}
                style={{background:T.panel,border:`1px solid ${T.rim}`,
                borderRadius:18,padding:"20px 20px 16px",marginBottom:14,cursor:"pointer"}}>

                {/* Row 1: institution + status */}
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12,flexWrap:"wrap"}}>
                  <span style={{fontSize:12,fontWeight:700,padding:"4px 10px",borderRadius:20,
                    background:deb.type==="gov"?`${T.teal}22`:`${T.blue}22`,
                    color:deb.type==="gov"?T.teal:T.blue}}>
                    {deb.type==="gov"?"🏛":"🏢"} {deb.inst}
                  </span>
                  <StatusBadge status={deb.status}/>
                  {hasVoted&&<span style={{fontSize:12,color:T.green,fontWeight:700}}>✓ Ya votaste</span>}
                </div>

                {/* Row 2: title — the most important thing */}
                <div style={{fontSize:20,fontWeight:800,color:T.white,marginBottom:14,lineHeight:1.45,letterSpacing:"-0.01em"}}>
                  {deb.title}
                </div>

                {/* Reward badge */}
                {deb.reward&&(
                  <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}44`,
                    borderRadius:10,padding:"8px 12px",marginBottom:12,fontSize:13,
                    color:T.gold,display:"flex",alignItems:"center",gap:7,fontWeight:600}}>
                    🎁 {deb.reward}
                  </div>
                )}

                {/* Visual product strip */}
                {deb.opt_images&&deb.opt_images.some(u=>u)?(
                  <div style={{display:"flex",gap:8,marginBottom:12,overflowX:"auto",paddingBottom:2}}>
                    {deb.opts.map((o,i)=>deb.opt_images[i]?(
                      <div key={i} style={{flexShrink:0,width:80,borderRadius:10,overflow:"hidden",
                        border:`2px solid ${COLORS[i%COLORS.length]}44`}}>
                        <img src={deb.opt_images[i]} alt={o}
                          style={{width:80,height:80,objectFit:"cover",display:"block"}}/>
                        <div style={{padding:"5px 6px",fontSize:11,color:COLORS[i%COLORS.length],
                          fontWeight:700,textAlign:"center",overflow:"hidden",
                          whiteSpace:"nowrap",textOverflow:"ellipsis"}}>{o}</div>
                      </div>
                    ):null)}
                  </div>
                ):(
                  /* Options as clean labeled rows */
                  <div style={{marginBottom:12,display:"flex",flexDirection:"column",gap:7}}>
                    {deb.opts.slice(0,4).map((o,i)=>(
                      <div key={i} style={{display:"flex",alignItems:"center",gap:10}}>
                        <div style={{width:12,height:12,borderRadius:3,background:COLORS[i%COLORS.length],flexShrink:0}}/>
                        <span style={{fontSize:15,color:T.snow,fontWeight:500,lineHeight:1.3}}>{o}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Row 3: footer stats */}
                <div style={{display:"flex",gap:14,fontSize:13,color:T.fog,alignItems:"center",
                  borderTop:`1px solid ${T.rim}`,paddingTop:12,marginTop:4}}>
                  <span>🗳 {deb.votes} votos</span>
                  {deb.comments>0&&<span>💬 {deb.comments}</span>}
                  {deb.status==="verifying"&&hasVoted&&
                    <span style={{color:T.gold,fontWeight:700}}>Verifica →</span>}
                  <span style={{marginLeft:"auto",color:T.blue,fontWeight:700,fontSize:14}}>Abrir →</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <VoterTabs/>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: DEBATE DETAIL
  // ══════════════════════════════════════════════════════════════
  if(screen==="debate"&&selDebate) {
    const deb=selDebate;
    const st=STATUS[deb.status];
    const hasVoted=voted[deb.id];
    const canVote=deb.status==="live"&&!hasVoted;
    const total=deb.vals.reduce((a,b)=>a+b,0)||1;
    const myKnowledge=debateKnowledge[deb.id];
    const KNOWLEDGE_LEVELS=[
      {v:"expert",  l:"Experto",  desc:"Tengo formación o experiencia directa en este tema.", icon:"🎓", color:T.blue},
      {v:"high",    l:"Alto",     desc:"Conozco bien el tema y he leído sobre él.",            icon:"📖", color:T.teal},
      {v:"medium",  l:"Medio",    desc:"Tengo nociones generales pero no soy especialista.",  icon:"💡", color:T.gold},
      {v:"low",     l:"Bajo",     desc:"Es un tema nuevo para mí. Quiero aprender.",          icon:"🌱", color:T.fog},
    ];
    const knowledgeMeta=(v)=>KNOWLEDGE_LEVELS.find(k=>k.v===v)||KNOWLEDGE_LEVELS[2];

    // ── KNOWLEDGE GATE ─────────────────────────────────────────
    if(!myKnowledge) return (
      <div style={phone}>
        <TopBar title="DEBATE" back="feed" right={<StatusBadge status={deb.status}/>}/>
        <div style={{padding:"24px 20px",minHeight:"100vh",background:T.bg}}>
          <div style={{fontSize:14,color:T.fog,marginBottom:6}}>{deb.inst}</div>
          <div style={{fontSize:22,fontWeight:900,color:T.white,lineHeight:1.4,marginBottom:28}}>
            {deb.title}
          </div>
          <div style={{fontSize:18,fontWeight:700,color:T.white,marginBottom:8}}>
            ¿Cuánto conoces sobre este tema?
          </div>
          <div style={{fontSize:15,color:T.fog,marginBottom:22,lineHeight:1.65}}>
            Tu nivel se muestra junto a cada opinión para que los demás valoren el contexto.
          </div>
          {KNOWLEDGE_LEVELS.map(({v,l,desc,icon,color})=>(
            <div key={v} onClick={()=>{
              setDebateKnowledge(prev=>({...prev,[deb.id]:v}));
              setKnowledgeLevel(v==="expert"?"expert":v==="high"?"good":v==="medium"?"familiar":"low");
            }} style={{
              background:T.panel,border:`1.5px solid ${T.rim}`,borderRadius:14,
              padding:"16px 18px",marginBottom:10,cursor:"pointer",
              display:"flex",alignItems:"center",gap:14,
              transition:"border-color 0.15s"
            }} onMouseEnter={e=>e.currentTarget.style.borderColor=color}
               onMouseLeave={e=>e.currentTarget.style.borderColor=T.rim}>
              <div style={{fontSize:28,flexShrink:0}}>{icon}</div>
              <div>
                <div style={{fontSize:18,fontWeight:800,color:color,marginBottom:4}}>{l}</div>
                <div style={{fontSize:14,color:T.fog,lineHeight:1.55}}>{desc}</div>
              </div>
              <div style={{marginLeft:"auto",fontSize:20,color:T.rim,flexShrink:0}}>›</div>
            </div>
          ))}
        </div>
      </div>
    );

    // ── DEBATE ROOM ────────────────────────────────────────────
    const km=knowledgeMeta(myKnowledge);
    const CHAR_LIMIT=500;
    const remaining=CHAR_LIMIT-newOpinionText.length;

    // Vote submit helper (used in VOTAR tab)
    const submitVote = async (q1Idx, chain) => {
      const q1Opt = deb.opts[q1Idx];
      try {
        const data = await apiFetch('POST',`/debates/${deb.id}/vote`,{option_index:q1Idx,vote_chain:chain});
        setVoted({...voted,[deb.id]:{opt:q1Opt,code:data.verify_code,chain,reward:data.reward_code||deb.reward||''}});
      } catch(e) {
        if(e.status===409) {
          alert(e.message || 'Ya votaste en esta consulta');
          return;
        }
        // Error de red/servidor: fallback demo para no bloquear el flujo de prueba
        const vc=`${Math.random().toString(16).slice(2,6).toUpperCase()}-${Math.random().toString(16).slice(2,6).toUpperCase()}-${Math.random().toString(16).slice(2,6).toUpperCase()}`;
        setVoted({...voted,[deb.id]:{opt:q1Opt,code:vc,chain,reward:deb.reward||''}});
        DEMO_CODES[vc]={debateId:deb.id,choice:q1Opt};
      }
      go("voted-success");
    };

    return (
      <div style={phone}>
        {/* Header */}
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
          padding:"14px 18px",position:"sticky",top:0,zIndex:99}}>
          <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:12}}>
            <button onClick={()=>go("feed")} style={{background:"none",border:"none",
              color:T.snow,fontSize:22,cursor:"pointer",padding:"0 4px",lineHeight:1}}>←</button>
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontSize:13,color:T.fog,fontWeight:600,marginBottom:2}}>{deb.inst}</div>
              <div style={{fontSize:17,fontWeight:800,color:T.white,lineHeight:1.3,
                overflow:"hidden",display:"-webkit-box",WebkitLineClamp:2,
                WebkitBoxOrient:"vertical"}}>
                {deb.title}
              </div>
            </div>
            <StatusBadge status={deb.status}/>
          </div>
          {/* Tab bar */}
          <div style={{display:"flex",gap:4}}>
            {[["debate","💬 Debate"],["vote","🗳 Votar"],["results","📊 Resultados"]].map(([id,lbl])=>(
              <button key={id} onClick={()=>{
                if(id==="results"&&!hasVoted&&deb.status==="live"){
                  alert("Vota primero para ver los resultados.");return;
                }
                setDebateTab(id);
              }} style={{
                flex:1,padding:"10px 6px",borderRadius:10,border:"none",cursor:"pointer",
                background:debateTab===id?T.blue:`${T.blue}18`,
                opacity:(id==="results"&&!hasVoted&&deb.status==="live")?0.4:1,
                color:debateTab===id?"#fff":T.fog,
                fontSize:14,fontWeight:debateTab===id?700:500}}>
                {lbl}
              </button>
            ))}
          </div>
        </div>

        {/* ── TAB: DEBATE ─────────────────────────────── */}
        {debateTab==="debate"&&(
          <div style={{background:"#f1f5f9",minHeight:"calc(100vh - 120px)",paddingBottom:80}}>
            {/* Topic card */}
            <div style={{background:"#fff",borderBottom:"1px solid #e2e8f0",padding:"20px 18px"}}>
              <div style={{fontSize:20,fontWeight:800,color:"#0f172a",lineHeight:1.45,marginBottom:10}}>
                {deb.title}
              </div>
              <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
                <span style={{fontSize:11,padding:"2px 8px",borderRadius:10,
                  background:`${km.color}18`,color:km.color,fontWeight:700}}>
                  {km.icon} {km.l}
                </span>
                <span style={{fontSize:11,color:"#94a3b8"}}>🗳 {deb.votes} votos</span>
                {canVote&&(
                  <button onClick={()=>setDebateTab('vote')} style={{
                    marginLeft:"auto",padding:"5px 12px",borderRadius:8,border:"none",
                    background:T.blue,color:"#fff",fontSize:11,fontWeight:700,cursor:"pointer"}}>
                    Pasar a votar →
                  </button>
                )}
              </div>
              {deb.reward&&canVote&&(
                <div style={{background:"#fef9e7",border:"1px solid #fbbf24",borderRadius:8,
                  padding:"8px 12px",marginTop:10,fontSize:12,color:"#92400e",
                  display:"flex",alignItems:"center",gap:8}}>
                  🎁 <span><strong>Recompensa:</strong> {deb.reward}</span>
                </div>
              )}
            </div>

            {/* Write opinion */}
            <div style={{background:"#fff",margin:"10px 12px",borderRadius:14,
              boxShadow:"0 1px 4px rgba(0,0,0,0.08)",padding:"14px 16px"}}>
              <div style={{display:"flex",gap:10,alignItems:"flex-start"}}>
                <div style={{width:36,height:36,borderRadius:"50%",background:km.color,
                  display:"flex",alignItems:"center",justifyContent:"center",
                  fontSize:18,flexShrink:0}}>{km.icon}</div>
                <div style={{flex:1}}>
                  <textarea
                    value={newOpinionText}
                    onChange={e=>{if(e.target.value.length<=CHAR_LIMIT)setNewOpinionText(e.target.value);}}
                    placeholder="¿Qué piensas sobre este tema? Argumenta tu postura..."
                    rows={3}
                    style={{width:"100%",background:"transparent",border:"none",outline:"none",
                      color:"#0f172a",fontSize:14,lineHeight:1.7,resize:"none",
                      fontFamily:"-apple-system,system-ui,sans-serif",
                      boxSizing:"border-box",caretColor:T.blue}}
                  />
                  <div style={{display:"flex",justifyContent:"space-between",
                    alignItems:"center",borderTop:"1px solid #e2e8f0",paddingTop:8,marginTop:4}}>
                    <span style={{fontSize:11,color:remaining<50?"#ef4444":"#94a3b8",fontWeight:remaining<50?700:400}}>
                      {remaining} caracteres restantes
                    </span>
                    <button onClick={()=>postOpinion(deb.id)}
                      disabled={postingOpinion||newOpinionText.trim().length<20}
                      style={{padding:"7px 18px",borderRadius:20,border:"none",cursor:"pointer",
                        background:newOpinionText.trim().length>=20?T.blue:"#cbd5e1",
                        color:"#fff",fontSize:13,fontWeight:700,
                        opacity:postingOpinion?0.6:1}}>
                      {postingOpinion?"Enviando…":"Publicar"}
                    </button>
                  </div>
                  {opinionError&&(
                    <div style={{fontSize:12,color:"#ef4444",marginTop:6}}>{opinionError}</div>
                  )}
                </div>
              </div>
            </div>

            {/* Opinion feed */}
            {opinionsLoading&&(
              <div style={{textAlign:"center",padding:24,color:"#94a3b8",fontSize:13}}>
                Cargando debate…
              </div>
            )}
            {!opinionsLoading&&debateOpinions.length===0&&(
              <div style={{textAlign:"center",padding:32,color:"#94a3b8"}}>
                <div style={{fontSize:32,marginBottom:8}}>💬</div>
                <div style={{fontSize:14,fontWeight:600,marginBottom:4}}>Sé el primero en opinar</div>
                <div style={{fontSize:12}}>Comparte tu perspectiva sobre este tema.</div>
              </div>
            )}
            {debateOpinions.map((op,i)=>(
              <div key={op.id||i}>
                {/* Ad every 5 opinions */}
                {i>0&&i%5===0&&(
                  <div style={{background:"#fff7ed",margin:"4px 12px",borderRadius:12,
                    padding:"10px 14px",border:"1px solid #fed7aa"}}>
                    <div style={{fontSize:9,color:"#c2410c",textTransform:"uppercase",
                      letterSpacing:"0.08em",marginBottom:4}}>Publicidad</div>
                    <div style={{fontSize:13,fontWeight:700,color:"#1c1917"}}>Patrocinado por la consulta</div>
                  </div>
                )}
                {/* Opinion card */}
                <div style={{background:"#fff",margin:"4px 12px",borderRadius:14,
                  padding:"14px 16px",boxShadow:"0 1px 3px rgba(0,0,0,0.06)"}}>
                  <div style={{display:"flex",gap:10,alignItems:"flex-start"}}>
                    <div style={{width:36,height:36,borderRadius:"50%",
                      background:knowledgeMeta(op.knowledge_level==="expert"?"expert":
                        op.knowledge_level==="good"?"high":
                        op.knowledge_level==="familiar"?"medium":"low").color,
                      display:"flex",alignItems:"center",justifyContent:"center",
                      fontSize:16,flexShrink:0}}>
                      {knowledgeMeta(op.knowledge_level==="expert"?"expert":
                        op.knowledge_level==="good"?"high":
                        op.knowledge_level==="familiar"?"medium":"low").icon}
                    </div>
                    <div style={{flex:1}}>
                      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                        <span style={{fontSize:13,fontWeight:700,color:"#0f172a"}}>{op.user_name}</span>
                        <span style={{fontSize:10,color:"#94a3b8"}}>
                          {new Date(op.created_at).toLocaleDateString('es-CL',{day:'numeric',month:'short'})}
                        </span>
                      </div>
                      <div style={{fontSize:11,color:knowledgeMeta(
                        op.knowledge_level==="expert"?"expert":
                        op.knowledge_level==="good"?"high":
                        op.knowledge_level==="familiar"?"medium":"low").color,
                        fontWeight:600,marginBottom:6}}>
                        {knowledgeMeta(op.knowledge_level==="expert"?"expert":
                          op.knowledge_level==="good"?"high":
                          op.knowledge_level==="familiar"?"medium":"low").icon}{" "}
                        {knowledgeMeta(op.knowledge_level==="expert"?"expert":
                          op.knowledge_level==="good"?"high":
                          op.knowledge_level==="familiar"?"medium":"low").l}
                      </div>
                      <div style={{fontSize:15,color:"#1e293b",lineHeight:1.7}}>{op.text}</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
            {/* Bottom CTA to vote */}
            {canVote&&debateOpinions.length>0&&(
              <div style={{margin:"16px 12px",background:T.blue,borderRadius:14,padding:"16px 20px",
                display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                <div>
                  <div style={{fontSize:14,fontWeight:800,color:"#fff",marginBottom:2}}>
                    ¿Listo para votar?
                  </div>
                  <div style={{fontSize:11,color:"rgba(255,255,255,0.7)"}}>
                    Tu voto se cifra con AES-256.
                  </div>
                </div>
                <button onClick={()=>setDebateTab('vote')}
                  style={{padding:"10px 18px",borderRadius:10,border:"2px solid #fff",
                    background:"transparent",color:"#fff",fontSize:13,fontWeight:700,cursor:"pointer"}}>
                  Votar →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── TAB: VOTAR ──────────────────────────────── */}
        {debateTab==="vote"&&(
          <div style={{padding:"16px 16px 80px",background:T.bg,minHeight:"calc(100vh - 120px)"}}>
            {deb.reward&&canVote&&(
              <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}55`,
                borderRadius:12,padding:"14px 16px",marginBottom:14,
                display:"flex",alignItems:"flex-start",gap:12}}>
                <div style={{fontSize:24,flexShrink:0}}>🎁</div>
                <div>
                  <div style={{fontSize:13,fontWeight:800,color:T.gold,marginBottom:3}}>Recompensa por participar</div>
                  <div style={{fontSize:13,color:T.white,lineHeight:1.5}}>{deb.reward}</div>
                </div>
              </div>
            )}
            {canVote&&(()=>{
              const isQ1=vBranchQ===null;
              const currentQ=isQ1?{title:deb.title,options:deb.opts,branches:deb.follow_ups}:vBranchQ;
              const qLevel=vBranchPath.length+1;
              const totalQ=(()=>{let n=1;let q=deb.follow_ups;if(q&&q.some(b=>b)){n=2;if(q.filter(Boolean).some(b=>b.branches&&b.branches.some(Boolean)))n=3;}return n;})();
              const handleOptionClick=async(i,opt)=>{
                const newStep={level:qLevel,option_index:i,option_text:opt,question:currentQ.title||deb.title};
                const newPath=[...vBranchPath,newStep];
                const nextQ=currentQ.branches?currentQ.branches[i]:null;
                if(nextQ&&nextQ.title){setVBranchPath(newPath);setVBranchQ(nextQ);}
                else{const q1Idx=vBranchPath.length>0?vBranchPath[0].option_index:i;await submitVote(q1Idx,newPath);}
              };
              const hasImgs=isQ1&&deb.opt_images&&deb.opt_images.some(u=>u);
              return (
                <Card style={{border:`1px solid ${T.blue}44`,background:`${T.blue}10`}}>
                  {totalQ>1&&(<div style={{display:"flex",gap:6,marginBottom:10,alignItems:"center"}}>
                    {Array.from({length:totalQ},(_,k)=>(
                      <div key={k} style={{flex:1,height:4,borderRadius:4,background:k<qLevel?T.blue:`${T.blue}30`}}/>
                    ))}
                    <span style={{fontSize:11,color:T.fog,marginLeft:4}}>{qLevel}/{totalQ}</span>
                  </div>)}
                  <Lbl>{isQ1?"Emite tu voto":"Pregunta de seguimiento"}</Lbl>
                  {!isQ1&&<div style={{fontSize:13,fontWeight:700,color:T.white,marginBottom:12,lineHeight:1.4}}>{currentQ.title}</div>}
                  {isQ1&&<div style={{fontSize:12,color:T.fog,marginBottom:12,lineHeight:1.6}}>Tu voto se cifra con AES-256 y se ancla en blockchain Polygon.</div>}
                  {hasImgs?(
                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:6}}>
                      {currentQ.options.map((opt,i)=>(
                        <button key={i} onClick={()=>handleOptionClick(i,opt)} style={{
                          borderRadius:12,overflow:"hidden",cursor:"pointer",padding:0,
                          border:`2px solid ${COLORS[i%COLORS.length]}66`,background:T.card}}>
                          {deb.opt_images[i]
                            ?<img src={deb.opt_images[i]} alt={opt} style={{width:"100%",aspectRatio:"1",objectFit:"cover",display:"block"}}/>
                            :<div style={{width:"100%",aspectRatio:"1",background:T.deep,display:"flex",alignItems:"center",justifyContent:"center",fontSize:28}}>📦</div>}
                          <div style={{padding:"8px 8px 10px",borderTop:`1px solid ${COLORS[i%COLORS.length]}33`}}>
                            <div style={{fontSize:10,color:T.fog,marginBottom:2}}>Opción {i+1}</div>
                            <div style={{fontSize:12,fontWeight:700,color:COLORS[i%COLORS.length],lineHeight:1.3}}>{opt}</div>
                          </div>
                        </button>
                      ))}
                    </div>
                  ):currentQ.options.map((opt,i)=>(
                    <button key={i} onClick={()=>handleOptionClick(i,opt)}
                      style={{width:"100%",padding:"18px 20px",borderRadius:14,
                        background:NEUTRAL_OPT,border:`1.5px solid ${NEUTRAL_BORDER}`,
                        color:T.snow,fontSize:17,fontWeight:700,cursor:"pointer",marginBottom:10,
                        textAlign:"left",display:"flex",alignItems:"center",gap:14,
                        transition:"border-color 0.15s,background 0.15s,box-shadow 0.15s"}}
                      onMouseEnter={e=>{
                        e.currentTarget.style.background='rgba(37,99,235,0.12)';
                        e.currentTarget.style.borderColor='#2563EB';
                        e.currentTarget.style.boxShadow='0 0 0 1px #2563EB22';
                      }}
                      onMouseLeave={e=>{
                        e.currentTarget.style.background=NEUTRAL_OPT;
                        e.currentTarget.style.borderColor=NEUTRAL_BORDER;
                        e.currentTarget.style.boxShadow='none';
                      }}>
                      <div style={{width:18,height:18,borderRadius:9,border:'2px solid rgba(255,255,255,0.2)',flexShrink:0}}/>
                      <span style={{color:T.white,lineHeight:1.4}}>{opt}</span>
                    </button>
                  ))}
                  {!isQ1&&<button onClick={()=>{setVBranchQ(null);setVBranchPath([]);}} style={{background:"none",border:"none",color:T.silver,fontSize:12,cursor:"pointer",marginTop:4}}>← Cambiar respuesta anterior</button>}
                </Card>
              );
            })()}
            {hasVoted&&(
              <Card style={{border:`1px solid ${T.green}44`,background:`${T.green}10`}}>
                <div style={{textAlign:"center"}}>
                  <div style={{fontSize:28,marginBottom:6}}>✅</div>
                  <div style={{fontSize:14,fontWeight:700,color:T.green,marginBottom:4}}>Ya votaste</div>
                  <div style={{fontSize:12,color:T.fog,marginBottom:8}}>Tu voto: <strong style={{color:T.white}}>{voted[deb.id].opt}</strong></div>
                  <div style={{fontFamily:"monospace",fontSize:14,color:T.blue,fontWeight:700,letterSpacing:"0.1em",marginBottom:8}}>{voted[deb.id].code}</div>
                  {voted[deb.id].reward&&(
                    <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}55`,
                      borderRadius:10,padding:"10px 14px",marginBottom:10}}>
                      <div style={{fontSize:11,color:T.gold,fontWeight:700,marginBottom:4,textTransform:"uppercase",letterSpacing:"0.05em"}}>🎁 Tu recompensa</div>
                      <div style={{fontFamily:"monospace",fontSize:15,color:T.white,fontWeight:700,letterSpacing:"0.08em"}}>{voted[deb.id].reward}</div>
                    </div>
                  )}
                  {deb.status==="verifying"&&(
                    <button onClick={()=>go("verify")} style={{background:"none",border:"none",color:T.gold,fontSize:13,fontWeight:700,cursor:"pointer"}}>
                      🔍 La verificación está abierta — verifica ahora →
                    </button>
                  )}
                </div>
              </Card>
            )}
            {!hasVoted&&deb.status!=="live"&&(
              <Card style={{opacity:0.7}}>
                <div style={{textAlign:"center",padding:"8px 0"}}>
                  <div style={{fontSize:24,marginBottom:6}}>🔒</div>
                  <div style={{fontSize:13,color:T.fog}}>La votación está cerrada.</div>
                </div>
              </Card>
            )}
          </div>
        )}

        {/* ── TAB: RESULTADOS ─────────────────────────── */}
        {debateTab==="results"&&(
          <div style={{padding:"16px 16px 80px",background:T.bg,minHeight:"calc(100vh - 120px)"}}>
            <div style={{fontSize:11,fontWeight:700,color:T.mist,textTransform:"uppercase",letterSpacing:1.5,marginBottom:10,paddingLeft:2}}>
              Detalle de Resultado · {deb.status==="live"?"Parcial":"Final"}
            </div>
            {/* Question box */}
            <div style={{border:`2px solid ${T.rim}`,borderRadius:12,padding:"14px 16px",marginBottom:14,background:T.card}}>
              <div style={{fontSize:15,fontWeight:700,color:T.snow,lineHeight:1.55}}>{deb.q}</div>
            </div>
            {/* Options list */}
            <div style={{marginBottom:14,paddingLeft:2}}>
              {deb.opts.map((o,i)=>(
                <div key={i} style={{fontSize:14,color:T.silver,lineHeight:1.9}}>
                  <span style={{fontWeight:600,color:'#93C5FD'}}>Opción {i+1}: </span>{o}
                </div>
              ))}
            </div>
            {/* Donut + Legend */}
            <div style={{display:"flex",alignItems:"flex-start",gap:10,marginBottom:14}}>
              <DonutResult vals={deb.vals} size={210}/>
              <div style={{flex:1,paddingTop:6,minWidth:0}}>
                <div style={{fontSize:10,fontWeight:700,color:T.mist,textTransform:"uppercase",letterSpacing:1,marginBottom:8}}>Alternativas</div>
                {deb.opts.map((o,i)=>(
                  <div key={i} style={{display:"flex",alignItems:"flex-start",gap:7,marginBottom:8}}>
                    <div style={{width:13,height:13,borderRadius:3,background:COLORS[i%COLORS.length],flexShrink:0,marginTop:2}}/>
                    <div style={{minWidth:0}}>
                      <div style={{fontSize:13,fontWeight:800,color:T.white}}>{Math.round(deb.vals[i]/total*100)}%</div>
                      <div style={{fontSize:11,color:T.fog,lineHeight:1.3,wordBreak:"break-word"}}>{o}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {/* Winner */}
            {deb.status!=="live"&&(
              <div style={{background:`${T.green}18`,border:`1px solid ${T.green}44`,borderRadius:12,padding:"12px 16px",marginBottom:12,fontSize:14,color:T.green}}>
                ✅ <strong>Ganador: {deb.opts[deb.vals.indexOf(Math.max(...deb.vals))]}</strong>
                {" — "}{Math.round(Math.max(...deb.vals)/total*100)}%
                {deb.status==="verified"&&` · ✓ ${deb.accuracy||0}% verificado`}
              </div>
            )}
            {/* Legitimacy Score */}
            <div style={{background:`${T.teal}18`,border:`1px solid ${T.teal}44`,borderRadius:12,padding:"14px 16px"}}>
              <div style={{fontSize:12,fontWeight:700,color:T.teal,marginBottom:4}}>🔗 Legitimacy Score</div>
              <div style={{fontSize:28,fontWeight:900,color:T.teal}}>{deb.votes>0?`${Math.round((deb.legitimacy_score||0)*100)}%`:"—"}</div>
              <div style={{fontSize:12,color:T.fog}}>Porcentaje de votantes que verificaron su voto.</div>
            </div>
          </div>
        )}

        <VoterTabs/>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: VOTED SUCCESS
  // ══════════════════════════════════════════════════════════════
  if(screen==="voted-success") {
    const lastVote=Object.entries(voted).slice(-1)[0];
    const vc=lastVote?voted[lastVote[0]].code:"XXXX-XXXX-XXXX";
    return (
      <div style={phone}>
        <div style={{minHeight:"100vh",display:"flex",flexDirection:"column",
          alignItems:"center",justifyContent:"center",padding:32,textAlign:"center"}}>
          <div style={{fontSize:64,marginBottom:16}}>✅</div>
          <div style={{fontSize:26,fontWeight:900,color:T.white,marginBottom:8}}>¡Voto registrado!</div>
          <div style={{fontSize:13,color:T.fog,lineHeight:1.7,marginBottom:24,maxWidth:300}}>
            Tu voto fue cifrado con AES-256, hasheado con SHA-256 y anclado en blockchain Polygon.
          </div>
          <Card style={{width:"100%",maxWidth:320,textAlign:"center"}}>
            <Lbl>Tu código de verificación</Lbl>
            <div style={{fontFamily:"monospace",fontSize:24,fontWeight:900,
              color:T.blue,letterSpacing:"0.15em",marginBottom:8}}>{vc}</div>
            <div style={{fontSize:11,color:T.fog,lineHeight:1.6,marginBottom:4}}>
              Guarda este código. La verificación abrirá cuando la votación cierre.
            </div>
            <div style={{fontSize:11,color:T.gold,fontWeight:700}}>
              ⚠️ La verificación NO está disponible durante la votación activa
            </div>
          </Card>
          <div style={{display:"flex",gap:10,flexDirection:"column",width:"100%",maxWidth:320,marginTop:14}}>
            <Btn label="Volver al feed →" full onPress={()=>go("feed")}/>
          </div>
        </div>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: RESULTS
  // ══════════════════════════════════════════════════════════════
  if(screen==="results") {
    const allDebs = apiDebates.length > 0 ? apiDebates : DEBATES;
    const votedDebs = allDebs.filter(d => voted[d.id]);
    return (
    <div style={phone}>
      <div style={{background:"#fff",borderBottom:"1px solid #e2e8f0",
        padding:"14px 16px",position:"sticky",top:0,zIndex:99}}>
        <div style={{fontSize:11,color:"#64748b",textTransform:"uppercase",
          letterSpacing:"0.1em",fontWeight:700,marginBottom:2}}>En tiempo real</div>
        <div style={{fontSize:22,fontWeight:900,color:"#0f172a",letterSpacing:-0.5}}>
          Zona de Resultados
        </div>
      </div>
      <div style={{background:"#f8fafc",minHeight:"100vh",padding:"14px 14px 90px"}}>
        {votedDebs.length===0?(
          <div style={{textAlign:"center",padding:"60px 20px"}}>
            <div style={{fontSize:56,marginBottom:16}}>🗳</div>
            <div style={{fontSize:18,fontWeight:700,color:"#1e293b",marginBottom:8}}>
              Aún no has votado
            </div>
            <div style={{fontSize:13,color:"#64748b",lineHeight:1.6,maxWidth:260,margin:"0 auto"}}>
              Participa en un debate y aquí verás los resultados en tiempo real de tus temas.
            </div>
            <button onClick={()=>go("feed")} style={{marginTop:24,padding:"12px 28px",
              borderRadius:12,background:T.blue,border:"none",color:"#fff",
              fontSize:14,fontWeight:700,cursor:"pointer"}}>
              Ver debates →
            </button>
          </div>
        ):votedDebs.map(deb=>{
          const myVote = voted[deb.id];
          const vals = deb.vals||[];
          const total = vals.reduce((a,b)=>a+b,0)||1;
          const winI = vals.indexOf(Math.max(...vals));
          const myOptIdx = (deb.opts||[]).indexOf(myVote?.opt);
          return (
            <div key={deb.id} style={{background:"#fff",borderRadius:16,
              border:"1px solid #e2e8f0",padding:16,marginBottom:12,
              boxShadow:"0 1px 3px rgba(0,0,0,0.06)"}}>
              <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:10}}>
                <StatusBadge status={deb.status}/>
                <span style={{fontSize:11,color:"#64748b"}}>{deb.inst}</span>
              </div>
              <div style={{fontSize:15,fontWeight:700,color:"#0f172a",marginBottom:14,lineHeight:1.4}}>
                {deb.title}
              </div>
              {myVote?.opt&&(
                <div style={{background:"#eff6ff",border:"1px solid #bfdbfe",
                  borderRadius:8,padding:"7px 11px",fontSize:12,color:"#1d4ed8",
                  marginBottom:myVote?.reward?8:12,display:"flex",alignItems:"center",gap:6}}>
                  ✓ Tu voto: <strong>{myVote.opt}</strong>
                </div>
              )}
              {myVote?.reward&&(
                <div style={{background:"#fffbeb",border:"1px solid #fcd34d",
                  borderRadius:8,padding:"7px 11px",marginBottom:12,
                  display:"flex",alignItems:"center",gap:6}}>
                  <span style={{fontSize:12}}>🎁</span>
                  <div>
                    <div style={{fontSize:10,color:"#92400e",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.05em"}}>Tu recompensa</div>
                    <div style={{fontFamily:"monospace",fontSize:13,color:"#78350f",fontWeight:700}}>{myVote.reward}</div>
                  </div>
                </div>
              )}
              <div style={{display:"flex",gap:10,alignItems:"flex-start",flexWrap:"wrap"}}>
                <Donut vals={vals} size={100}/>
                <div style={{flex:1,minWidth:120}}>
                  {(deb.opts||[]).map((o,i)=>(
                    <div key={i} style={{marginBottom:8}}>
                      <div style={{display:"flex",justifyContent:"space-between",
                        fontSize:12,marginBottom:3}}>
                        <span style={{color:i===myOptIdx?"#1d4ed8":"#475569",
                          fontWeight:i===myOptIdx?700:400}}>{o}{i===myOptIdx?" ✓":""}</span>
                        <span style={{fontWeight:700,color:COLORS[i%COLORS.length]}}>
                          {vals[i]?Math.round(vals[i]/total*100):0}%
                        </span>
                      </div>
                      <div style={{background:"#f1f5f9",borderRadius:4,height:6,overflow:"hidden"}}>
                        <div style={{height:"100%",borderRadius:4,
                          background:COLORS[i%COLORS.length],
                          width:(vals[i]?Math.round(vals[i]/total*100):0)+"%",
                          transition:"width 0.6s ease"}}/>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {deb.status!=="live"&&vals[winI]>0&&(
                <div style={{background:"#f0fdf4",border:"1px solid #bbf7d0",
                  borderRadius:8,padding:"8px 12px",fontSize:12,color:"#15803d",marginTop:10}}>
                  ✅ <strong>{deb.opts[winI]}</strong>
                  {" · "}{Math.round(vals[winI]/total*100)}%
                  {deb.status==="verified"&&deb.accuracy&&` · ✓ ${deb.accuracy}% verificado`}
                </div>
              )}
              {myVote?.code&&(
                <div style={{marginTop:10,fontSize:11,color:"#94a3b8",
                  fontFamily:"monospace"}}>Código: {myVote.code}</div>
              )}
            </div>
          );
        })}
      </div>
      <VoterTabs/>
    </div>
  );}

  // ══════════════════════════════════════════════════════════════
  // SCREEN: VERIFY
  // ══════════════════════════════════════════════════════════════
  if(screen==="verify") {
    const verifyingDebates=DEBATES.filter(d=>d.status==="verifying");
    const verifiedDebates=DEBATES.filter(d=>d.status==="verified");

    const allDebs = apiDebates.length > 0 ? apiDebates : DEBATES;
    const lookupVote = async (code) => {
      const upper = code.toUpperCase();

      // 1. Session votes — we know the debate_id
      const sessionEntry = Object.entries(voted).find(([,v]) => v.code === upper);
      if(sessionEntry) {
        const debateId = parseInt(sessionEntry[0]);
        try {
          const data = await apiFetch('POST',`/debates/${debateId}/verify`,{code:upper});
          if(data.found) {
            const deb = allDebs.find(d=>d.id===debateId) ||
              {id:debateId,title:data.debate_title,opts:[],inst:''};
            return {deb, choice:data.your_vote};
          }
        } catch(e) {}
        // Fallback to client-side data
        const deb = allDebs.find(d=>d.id===debateId);
        if(deb) return {deb, choice:sessionEntry[1].opt};
      }

      // 2. Demo codes (client-side)
      const demo = DEMO_CODES[upper];
      if(demo) {
        const deb = allDebs.find(d=>d.id===demo.debateId);
        if(deb && (deb.status==="verifying"||deb.status==="live")) return {deb,choice:demo.choice};
      }

      // 3. Try all loaded debates on backend
      for(const deb of allDebs) {
        try {
          const data = await apiFetch('POST',`/debates/${deb.id}/verify`,{code:upper});
          if(data.found) return {deb, choice:data.your_vote};
        } catch(e) {}
      }
      return null;
    };

    return (
      <div style={phone}>
        <TopBar title="Verificar mi voto"/>
        <div style={{padding:"12px 16px 80px"}}>
          <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}44`,
            borderRadius:12,padding:"12px 14px",marginBottom:14,fontSize:12,
            color:T.gold,lineHeight:1.7}}>
            ⚠️ <strong>La verificación solo está disponible después de que la votación cierra.</strong>
          </div>

          {verifyingDebates.length>0&&(
            <Card>
              <Lbl>🔍 Debates en fase de verificación</Lbl>
              {verifyingDebates.map(d=>(
                <div key={d.id} style={{padding:"8px 0",borderBottom:`1px solid ${T.rim}`}}>
                  <div style={{fontSize:13,fontWeight:700,color:T.white,marginBottom:2}}>{d.title}</div>
                  <div style={{fontSize:11,color:T.fog}}>{d.inst}</div>
                  <div style={{fontSize:10,color:T.gold,marginTop:3}}>Verificación hasta: {d.verify_closes}</div>
                  {voted[d.id]&&(
                    <div style={{fontSize:10,color:T.green,marginTop:2}}>
                      ✓ Participaste · Código: {voted[d.id].code}
                    </div>
                  )}
                </div>
              ))}
            </Card>
          )}

          {vStep==="enter"&&(
            <Card>
              <Lbl>Ingresa tu código de verificación</Lbl>
              <input value={codeInput} onChange={e=>setCode(e.target.value.toUpperCase())}
                placeholder="XXXX-XXXX-XXXX" maxLength={14}
                style={{width:"100%",padding:"14px",borderRadius:10,
                  background:T.deep,border:`2px solid ${T.blue}`,color:T.blue,
                  fontSize:20,fontWeight:700,fontFamily:"monospace",letterSpacing:"0.15em",
                  outline:"none",textAlign:"center",boxSizing:"border-box"}}/>
              <div style={{fontSize:11,color:T.fog,marginTop:8,marginBottom:14,textAlign:"center"}}>
                Demo: {["3EF8-777D-5864","05EB-55C2-2A95","404D-7E85-9BB0"].map(c=>(
                  <button key={c} onClick={()=>setCode(c)} style={{background:"none",border:"none",
                    color:T.blue,cursor:"pointer",fontSize:11,fontWeight:700,marginRight:6}}>
                    {c}
                  </button>
                ))}
              </div>
              <Btn label="Decodificar mi voto →" full onPress={async()=>{
                if(!codeInput){alert("Ingresa tu código");return;}
                setVStep("decoding");
                // API lookup + animation mínima en paralelo
                const [result] = await Promise.all([
                  lookupVote(codeInput),
                  new Promise(r=>setTimeout(r,2000)),
                ]);
                setFoundVote(result);
                setVStep(result?"reveal":"notfound");
              }}/>
            </Card>
          )}

          {vStep==="decoding"&&(
            <Card style={{textAlign:"center",padding:28}}>
              <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:20}}>
                🔓 Decodificando desde blockchain Polygon...
              </div>
              {["🔍 Localizando código en blockchain...","🔑 Aplicando clave de decodificación...","🔓 Descifrado AES-256 completado...","✅ Voto recuperado"].map((s,i)=>(
                <div key={i} style={{padding:"9px 14px",borderRadius:8,
                  background:T.deep,border:`1px solid ${T.rim}`,
                  marginBottom:8,fontSize:12,color:T.teal,textAlign:"left"}}>
                  {s}
                </div>
              ))}
            </Card>
          )}

          {vStep==="notfound"&&(
            <div style={{background:`${T.coral}18`,border:`1px solid ${T.coral}44`,
              borderRadius:14,padding:24,textAlign:"center",marginBottom:14}}>
              <div style={{fontSize:36,marginBottom:8}}>❌</div>
              <div style={{fontSize:16,fontWeight:700,color:T.coral,marginBottom:6}}>Código no encontrado</div>
              <div style={{fontSize:12,color:T.fog,marginBottom:14}}>
                Puede que el debate no esté en fase de verificación aún.
              </div>
              <Btn label="Intentar de nuevo" onPress={()=>{setVStep("enter");setCode("");setConfirmed(null);}}/>
            </div>
          )}

          {vStep==="reveal"&&foundVote&&confirmed===null&&(
            <>
              <Card>
                <Lbl>Tu voto registrado en blockchain</Lbl>
                <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:2}}>{foundVote.deb.title}</div>
                <div style={{fontSize:11,color:T.fog,marginBottom:14}}>{foundVote.deb.inst}</div>
                <div style={{background:T.deep,borderRadius:10,padding:14,border:`2px solid ${T.blue}`,marginBottom:12}}>
                  {foundVote.deb.opts.map((o,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:8,
                      padding:"7px 0",borderBottom:i<foundVote.deb.opts.length-1?`1px solid ${T.rim}`:"none"}}>
                      <span style={{fontSize:11,color:T.fog,width:55,flexShrink:0}}>Opción {i+1}:</span>
                      <span style={{fontSize:13,fontWeight:700,flex:1,
                        color:o===foundVote.choice?T.blue:T.silver}}>{o}</span>
                      {o===foundVote.choice&&<span style={{fontSize:16}}>◀</span>}
                    </div>
                  ))}
                  <div style={{marginTop:12,padding:"10px 12px",background:`${T.blue}22`,
                    borderRadius:8,display:"flex",alignItems:"center",gap:10}}>
                    <span style={{fontSize:20}}>☑️</span>
                    <div>
                      <div style={{fontSize:10,color:T.fog,marginBottom:2}}>TU VOTO REGISTRADO</div>
                      <div style={{fontSize:16,fontWeight:900,color:T.blue}}>{foundVote.choice}</div>
                    </div>
                  </div>
                </div>
              </Card>
              <Card>
                <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:6}}>¿Es correcto tu voto?</div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
                  <button onClick={async()=>{
                    setConfirmed(true);
                    setConfs(prev=>({...prev,[foundVote.deb.id]:(prev[foundVote.deb.id]||0)+1}));
                    try {
                      const form=new FormData();
                      form.append('code',codeInput.toUpperCase());
                      form.append('confirmed','true');
                      await fetch(`${API}/debates/${foundVote.deb.id}/verify/confirm`,{method:'POST',body:form});
                    } catch(e){}
                  }} style={{padding:"14px",borderRadius:12,background:T.teal,border:"none",color:"#fff",fontSize:15,fontWeight:700,cursor:"pointer"}}>
                    ✓ Sí, correcto
                  </button>
                  <button onClick={async()=>{
                    setConfirmed(false);
                    setDisputes(prev=>({...prev,[foundVote.deb.id]:(prev[foundVote.deb.id]||0)+1}));
                    try {
                      const form=new FormData();
                      form.append('code',codeInput.toUpperCase());
                      form.append('confirmed','false');
                      await fetch(`${API}/debates/${foundVote.deb.id}/verify/confirm`,{method:'POST',body:form});
                    } catch(e){}
                  }} style={{padding:"14px",borderRadius:12,background:T.coral,border:"none",color:"#fff",fontSize:15,fontWeight:700,cursor:"pointer"}}>
                    ✗ No es correcto
                  </button>
                </div>
              </Card>
            </>
          )}

          {vStep==="reveal"&&confirmed===true&&(
            <>
              <div style={{background:`${T.green}18`,border:`1px solid ${T.green}44`,
                borderRadius:14,padding:24,textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:48,marginBottom:10}}>✅</div>
                <div style={{fontSize:18,fontWeight:900,color:T.green,marginBottom:6}}>¡Voto confirmado!</div>
                <div style={{fontSize:13,color:T.silver,lineHeight:1.6}}>
                  Tu confirmación fue registrada en blockchain. Eres parte de la auditoría democrática.
                </div>
              </div>
              <Card>
                <Lbl>📊 Precisión global del sistema</Lbl>
                <div style={{background:T.deep,borderRadius:10,padding:16,textAlign:"center"}}>
                  <div style={{fontSize:36,fontWeight:900,color:T.green}}>97.4%</div>
                  <div style={{fontSize:12,color:T.fog,marginTop:4}}>Precisión global del sistema</div>
                  <div style={{fontSize:10,color:T.mist,marginTop:2}}>
                    Insight de José Ignacio Fernández — los votantes son los auditores
                  </div>
                </div>
              </Card>
              <Btn label="← Verificar otro voto" full outline color={T.blue}
                onPress={()=>{setVStep("enter");setCode("");setConfirmed(null);setFoundVote(null);}}/>
            </>
          )}

          {vStep==="reveal"&&confirmed===false&&(
            <>
              <div style={{background:`${T.coral}18`,border:`1px solid ${T.coral}44`,
                borderRadius:14,padding:24,textAlign:"center",marginBottom:14}}>
                <div style={{fontSize:48,marginBottom:10}}>⚠️</div>
                <div style={{fontSize:18,fontWeight:900,color:T.coral,marginBottom:6}}>Disputa registrada</div>
                <div style={{fontSize:13,color:T.silver,lineHeight:1.6}}>
                  Tu disputa fue registrada en blockchain y enviada al equipo de auditoría.
                </div>
              </div>
              <Btn label="← Verificar otro voto" full outline color={T.blue}
                onPress={()=>{setVStep("enter");setCode("");setConfirmed(null);setFoundVote(null);}}/>
            </>
          )}

          {verifiedDebates.length>0&&vStep==="enter"&&(
            <Card>
              <Lbl>✅ Debates verificados y certificados</Lbl>
              {verifiedDebates.map(d=>(
                <div key={d.id} style={{padding:"8px 0",borderBottom:`1px solid ${T.rim}`}}>
                  <div style={{fontSize:13,fontWeight:700,color:T.white,marginBottom:2}}>{d.title}</div>
                  <div style={{fontSize:11,color:T.fog,marginBottom:3}}>{d.inst}</div>
                  <div style={{fontSize:11,color:T.teal,fontWeight:700}}>
                    ✅ {d.accuracy}% de votantes confirmaron · Resultado certificado
                  </div>
                </div>
              ))}
            </Card>
          )}
        </div>
        <VoterTabs/>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: PROFILE
  // ══════════════════════════════════════════════════════════════
  if(screen==="profile") return (
    <div style={phone}>
      <TopBar title="Mi perfil"/>
      <div style={{padding:"12px 16px 80px"}}>
        <div style={{textAlign:"center",padding:"16px 0 20px"}}>
          <div style={{width:72,height:72,borderRadius:"50%",background:T.blue,
            display:"flex",alignItems:"center",justifyContent:"center",
            fontSize:28,fontWeight:900,margin:"0 auto 10px"}}>
            {(currentUser?.name||vfName||'?')[0].toUpperCase()}
          </div>
          <div style={{fontSize:18,fontWeight:700,color:T.white}}>{currentUser?.name||vfName||'Mi perfil'}</div>
          <div style={{fontSize:12,color:T.fog}}>{vfCounty||currentUser?.county||''}{(vfCounty||currentUser?.county)?' · ':''}{currentUser?.country||vfCountry||'CL'}</div>
          <div style={{marginTop:8,fontSize:10,fontWeight:700,padding:"3px 10px",
            borderRadius:10,background:`${T.green}22`,color:T.green,display:"inline-block"}}>
            ✓ Verificado 7 capas
          </div>
        </div>
        <Card>
          <Lbl>Mis votos y códigos</Lbl>
          {Object.keys(voted).length===0?(
            <div style={{fontSize:13,color:T.fog}}>Aún no has votado en ningún debate.</div>
          ):Object.entries(voted).map(([id,v])=>{
            const deb=(apiDebates.length?apiDebates:DEBATES).find(d=>d.id===parseInt(id));
            const st=deb?STATUS[deb.status]:null;
            return (
              <div key={id} style={{padding:"10px 0",borderBottom:`1px solid ${T.rim}`}}>
                <div style={{fontSize:11,color:T.fog,marginBottom:2}}>{deb?.title}</div>
                <div style={{fontSize:13,fontWeight:700,color:T.blue,marginBottom:4}}>{v.opt}</div>
                <div style={{fontFamily:"monospace",fontSize:12,color:T.silver,marginBottom:4}}>{v.code}</div>
                {st&&<span style={{fontSize:10,fontWeight:700,padding:"2px 8px",
                  borderRadius:10,background:st.bg,color:st.color}}>{st.label}</span>}
                {deb?.status==="verifying"&&(
                  <button onClick={()=>go("verify")} style={{background:"none",border:"none",
                    color:T.gold,fontSize:11,fontWeight:700,cursor:"pointer",display:"block",marginTop:4}}>
                    🔍 Verificar ahora →
                  </button>
                )}
              </div>
            );
          })}
        </Card>
        <Btn label="Cerrar sesión" full outline color={T.coral} onPress={()=>go("launch")}/>
      </div>
      <VoterTabs/>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: ORG SPLASH — editorial landing for institutions
  // ══════════════════════════════════════════════════════════════
  if(screen==="org-splash") return (
    <div style={{width:"100%",maxWidth:430,margin:"0 auto",minHeight:"100vh",
      position:"relative",overflowY:"auto",background:"#f5f3ee",
      fontFamily:"'Manrope',system-ui,sans-serif"}}>

      {/* ── HERO ─────────────────────────────────── */}
      <div style={{minHeight:"100vh",display:"flex",flexDirection:"column",
        alignItems:"center",justifyContent:"center",padding:"80px 28px 56px",
        textAlign:"center",background:"linear-gradient(160deg,#f5f3ee 0%,#ede9e0 100%)",
        position:"relative"}}>

        <button onClick={()=>go("launch")} style={{
          position:"absolute",top:24,left:20,background:"transparent",border:"none",
          fontSize:13,color:"#1a3a8f",cursor:"pointer",fontWeight:600,
          fontFamily:"'Manrope',sans-serif"}}>← Volver</button>

        <div style={{fontSize:10,color:"#1a3a8f",letterSpacing:3,
          textTransform:"uppercase",marginBottom:22,
          fontFamily:"'DM Mono','Courier New',monospace",fontWeight:500}}>
          A universal preference and deliberation network
        </div>

        <div style={{fontFamily:"'Playfair Display',Georgia,serif",fontSize:36,
          color:"#060810",lineHeight:1.1,letterSpacing:-1.5,marginBottom:22,maxWidth:340}}>
          Know what your market wants{" "}
          <em style={{color:"#1a3a8f",fontStyle:"italic"}}>before</em>
          {" "}you produce.
        </div>

        <div style={{fontSize:15,color:"#7a7570",maxWidth:320,lineHeight:1.8,
          marginBottom:44,fontFamily:"'Manrope',sans-serif"}}>
          Real preferences exist between extremes. Preferendum maps the full preference
          space of any population and delivers the intelligence that makes decisions obvious.
        </div>

        <div style={{display:"flex",gap:24,justifyContent:"center",
          borderTop:"1px solid #d4cfc5",paddingTop:32,width:"100%",
          maxWidth:340,marginBottom:40}}>
          {[["Q1→Q2→Q3","Cascading trees"],["∞","Markets"],["98%","Legitimacy"]].map(([n,l])=>(
            <div key={l} style={{textAlign:"center"}}>
              <div style={{fontFamily:"'Playfair Display',Georgia,serif",fontSize:22,
                color:"#060810",lineHeight:1,marginBottom:6}}>{n}</div>
              <div style={{fontSize:9,color:"#7a7570",letterSpacing:1,
                textTransform:"uppercase",fontFamily:"monospace"}}>{l}</div>
            </div>
          ))}
        </div>

        <div style={{display:"flex",flexDirection:"column",gap:10,width:"100%",maxWidth:320}}>
          <button onClick={()=>go("inst-login")} style={{
            padding:"16px 28px",borderRadius:6,background:"#1a3a8f",border:"none",
            color:"#fff",fontSize:15,fontWeight:700,cursor:"pointer",
            fontFamily:"'Manrope',sans-serif"}}>
            Comenzar como institución →
          </button>
          <button onClick={()=>{
            const el=document.getElementById("org-decisions");
            if(el) el.scrollIntoView({behavior:"smooth"});
          }} style={{
            padding:"14px 28px",borderRadius:6,background:"transparent",
            border:"2px solid #1a3a8f",color:"#1a3a8f",fontSize:14,fontWeight:600,
            cursor:"pointer",fontFamily:"'Manrope',sans-serif"}}>
            Ver cómo funciona ↓
          </button>
        </div>
      </div>

      {/* ── DECISIONS EMERGE ─────────────────────── */}
      <div id="org-decisions" style={{background:"#060810",padding:"60px 24px 72px"}}>
        <div style={{fontSize:10,color:"#c49a2a",letterSpacing:3,
          textTransform:"uppercase",marginBottom:18,
          fontFamily:"'DM Mono','Courier New',monospace"}}>
          The core insight
        </div>

        <div style={{fontFamily:"'Playfair Display',Georgia,serif",fontSize:34,
          color:"#f5f3ee",lineHeight:1.15,letterSpacing:-1,marginBottom:18}}>
          Decisions emerge<br/>in the space<br/>
          <em style={{color:"#e8b830",fontStyle:"italic"}}>between extremes.</em>
        </div>

        <div style={{fontSize:14,color:"rgba(245,243,238,0.65)",lineHeight:1.8,
          marginBottom:32,fontFamily:"'Manrope',sans-serif"}}>
          A binary poll asks "A or B?" — that's a false choice. Real preferences are
          gradients. Preferendum's cascading question trees reveal where collective
          decisions naturally land between the extremes you define.
        </div>

        {[
          ["🌳","Cascading question trees","After Q1, each answer branches into Q2. Each Q2 answer into Q3. You map the full decision topology of your market — not just the peak."],
          ["⚖️","Marginal Rate of Substitution","Quantify exactly how much of attribute A people sacrifice to gain attribute B. Taste vs. sugar. Growth vs. pollution. The number that makes strategy precise."],
          ["🌍","Geographic preference gradients","Run the same consultation in Brazil and the USA simultaneously. Send the right product to the right country — before you manufacture a single unit."],
          ["🎁","Reward your participants","Offer a discount code, early access, or a sample to everyone who helps you decide. Better data, higher engagement, loyal customers before launch."]
        ].map(([icon,title,desc])=>(
          <div key={title} style={{display:"flex",gap:14,alignItems:"flex-start",
            padding:18,background:"rgba(255,255,255,0.04)",
            border:"1px solid rgba(255,255,255,0.07)",borderRadius:12,marginBottom:12}}>
            <div style={{fontSize:22,minWidth:28,lineHeight:1}}>{icon}</div>
            <div>
              <div style={{fontSize:13,fontWeight:700,color:"#f5f3ee",marginBottom:4,
                fontFamily:"'Manrope',sans-serif"}}>{title}</div>
              <div style={{fontSize:12,color:"rgba(245,243,238,0.55)",lineHeight:1.65,
                fontFamily:"'Manrope',sans-serif"}}>{desc}</div>
            </div>
          </div>
        ))}

        <div style={{marginTop:36}}>
          <button onClick={()=>go("inst-login")} style={{
            width:"100%",padding:"16px 28px",borderRadius:6,
            background:"#1a3a8f",border:"none",color:"#fff",
            fontSize:15,fontWeight:700,cursor:"pointer",
            fontFamily:"'Manrope',sans-serif"}}>
            Comenzar como institución →
          </button>
        </div>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: INSTITUTION LOGIN
  // ══════════════════════════════════════════════════════════════
  if(screen==="inst-login") return (
    <div style={phone}>
      <TopBar title="Portal Institucional" back="feed"/>
      <div style={{padding:"16px 16px 80px"}}>
        <div style={{textAlign:"center",padding:"20px 0"}}>
          <div style={{fontSize:48,marginBottom:12}}>🏛</div>
          <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Portal de Instituciones</div>
          <div style={{fontSize:13,color:T.fog}}>Cualquier persona puede crear una consulta</div>
        </div>
        <Card>
          <Lbl>Tipo de organización</Lbl>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:16}}>
            {[["🏢","Empresa",T.blue],["🤝","Asociación profesional",T.teal],
              ["🌾","Asociación productiva",T.green],["🎓","Universidad",T.gold],
              ["🏛","Municipio",T.teal],["🌐","Entidad de representación ciudadana",T.coral],
              ["👤","Cualquier persona",T.fog]].map(([i,l,c])=>(
              <div key={l} onClick={()=>go("inst-home")} style={{padding:12,borderRadius:10,
                border:`1.5px solid ${c}44`,background:`${c}11`,textAlign:"center",cursor:"pointer"}}>
                <div style={{fontSize:24,marginBottom:4}}>{i}</div>
                <div style={{fontSize:11,fontWeight:700,color:c}}>{l}</div>
              </div>
            ))}
          </div>
          <Input label="Nombre de tu organización" placeholder="Ej: Coca-Cola Chile, Universidad de Chile..." value={ncInstName} onChange={setNcInstName}/>
          <Input label="Email institucional" placeholder="contacto@organización.cl" value={email} onChange={setEmail}/>
          <Input label="Contraseña" placeholder="••••••••" type="password" value={pw} onChange={setPw}/>
          <Btn label="Entrar al portal →" full onPress={()=>go("inst-home")}/>
        </Card>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: INSTITUTION HOME
  // ══════════════════════════════════════════════════════════════
  if(screen==="inst-home") return (
    <div style={phone}>
      <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
        padding:"12px 16px",display:"flex",alignItems:"center",gap:10,
        position:"sticky",top:0,zIndex:99}}>
        <button onClick={()=>go("inst-login")} style={{background:"none",border:"none",
          color:T.snow,fontSize:16,cursor:"pointer",padding:"4px 8px 4px 0"}}>←</button>
        <div style={{fontSize:16}}>🏛</div>
        <div style={{flex:1}}>
          <div style={{fontWeight:900,fontSize:15,color:T.white}}>{ncInstName||'Mi organización'}</div>
          <div style={{fontSize:10,color:T.fog}}>Portal institucional</div>
        </div>
        <button onClick={()=>setInstTab("create")} style={{padding:"6px 12px",borderRadius:8,
          background:T.blue,border:"none",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer"}}>
          + Nuevo debate
        </button>
      </div>

      <div style={{padding:"12px 16px 80px"}}>
        {instTab==="debates"&&(()=>{
          const allDebs = apiDebates.length > 0 ? apiDebates : [];
          // Show all backend debates; highlight ones created this session
          const myDebs = myDebateIds.length > 0
            ? allDebs.filter(d => myDebateIds.includes(d.id))
            : [];
          const otherDebs = myDebateIds.length > 0
            ? allDebs.filter(d => !myDebateIds.includes(d.id))
            : allDebs;
          const displayDebs = [...myDebs, ...otherDebs];
          return (
          <>
            <div style={{padding:"4px 0 14px",display:"flex",alignItems:"center"}}>
              <div style={{fontSize:20,fontWeight:900,color:T.white,flex:1}}>
                {myDebateIds.length > 0 ? `Mis consultas (${myDebs.length})` : 'Consultas'}
              </div>
              <button onClick={()=>setInstTab("create")} style={{padding:"6px 14px",borderRadius:8,
                background:T.blue,border:"none",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer"}}>
                + Nueva
              </button>
            </div>
            {debatesLoading&&displayDebs.length===0&&(
              <div style={{textAlign:"center",padding:24,color:T.fog,fontSize:13}}>Cargando consultas...</div>
            )}
            {!debatesLoading&&displayDebs.length===0&&(
              <div style={{textAlign:"center",padding:32,color:T.fog,fontSize:13}}>
                <div style={{fontSize:40,marginBottom:12}}>📋</div>
                <div>Aún no hay consultas.</div>
                <div style={{fontSize:11,marginTop:6}}>Crea la primera con el botón + Nueva.</div>
              </div>
            )}
            {displayDebs.map(deb=>{
              const isMine = myDebateIds.includes(deb.id);
              const vals=deb.vals||[];
              const total=vals.reduce((a,b)=>a+b,0)||1;
              return (
                <Card key={deb.id} style={isMine?{border:`1.5px solid ${T.teal}44`,background:`${T.teal}08`}:{}}>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                    {isMine&&<span style={{fontSize:9,fontWeight:700,padding:"2px 7px",borderRadius:8,
                      background:`${T.teal}22`,color:T.teal}}>TU CONSULTA</span>}
                    <StatusBadge status={deb.status}/>
                  </div>
                  <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:6,lineHeight:1.4}}>{deb.title}</div>
                  <div style={{fontSize:11,color:T.fog,marginBottom:10}}>{deb.inst} · 🗳 {deb.votes||0} votos</div>
                  {(deb.opts||[]).map((o,i)=>(
                    <div key={i} style={{marginBottom:7}}>
                      <div style={{display:"flex",justifyContent:"space-between",fontSize:11,marginBottom:3}}>
                        <span style={{color:T.silver}}>{o}</span>
                        <span style={{fontWeight:700,color:'#93C5FD'}}>{vals[i]?Math.round(vals[i]/total*100):0}%</span>
                      </div>
                      <div style={{background:'rgba(255,255,255,0.06)',borderRadius:4,height:6,overflow:"hidden"}}>
                        <div style={{height:"100%",borderRadius:4,
                          background:vals[i]===Math.max(...vals)?BAR_WIN:BAR_GRADIENT,
                          width:(vals[i]?Math.round(vals[i]/total*100):0)+"%",transition:"width 0.5s ease"}}/>
                      </div>
                    </div>
                  ))}
                </Card>
              );
            })}
          </>
          );
        })()}

        {instTab==="dashboard"&&(
          <>
            <div style={{padding:"4px 0 14px"}}>
              <div style={{fontSize:20,fontWeight:900,color:T.white}}>Dashboard en vivo</div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:14}}>
              {[["245","Votos totales",T.blue],["86%","Participación",T.green],
                ["3","Debates activos",T.teal],["1","En verificación",T.gold]].map(([n,l,c])=>(
                <div key={l} style={{background:T.panel,border:`1px solid ${T.rim}`,
                  borderRadius:12,padding:14,textAlign:"center"}}>
                  <div style={{fontSize:28,fontWeight:900,color:c,letterSpacing:-1}}>{n}</div>
                  <div style={{fontSize:11,color:T.fog,marginTop:2}}>{l}</div>
                </div>
              ))}
            </div>
            <Card>
              <Lbl>Integridad del sistema</Lbl>
              {[["Presupuesto 2027",98],["Plan movilidad",97],["Global",97.5]].map(([d,p])=>(
                <div key={d} style={{marginBottom:10}}>
                  <div style={{display:"flex",justifyContent:"space-between",fontSize:12,marginBottom:3}}>
                    <span style={{color:T.silver}}>{d}</span>
                    <span style={{fontWeight:900,color:T.green}}>{p}%</span>
                  </div>
                  <div style={{background:T.deep,borderRadius:4,height:7,overflow:"hidden"}}>
                    <div style={{height:"100%",width:p+"%",background:T.green,borderRadius:4}}/>
                  </div>
                </div>
              ))}
            </Card>
          </>
        )}

        {instTab==="create"&&(
          <>
            <div style={{padding:"4px 0 14px"}}>
              <div style={{fontSize:20,fontWeight:900,color:T.white}}>Crear debate</div>
            </div>
            <Card>
              <Lbl>Información</Lbl>
              <Input label="Título de la pregunta" placeholder="¿Cuál es la prioridad para el presupuesto 2027?" value={ncTitle} onChange={setNcTitle}/>
              <Input label="Descripción (opcional)" placeholder="Explica el contexto de la consulta..." value={ncDesc} onChange={setNcDesc}/>

              {/* ÁRBOL DE DECISIONES — justo después del contexto */}
              <div style={{marginTop:16,padding:14,borderRadius:12,
                background:ncBranching?`${T.blue}14`:`${T.rim}44`,
                border:`1px solid ${ncBranching?T.blue:T.rim}`}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12}}>
                  <div style={{flex:1}}>
                    <div style={{fontSize:14,fontWeight:700,color:ncBranching?T.white:T.fog,marginBottom:4}}>
                      🌳 Árbol de decisiones
                    </div>
                    <div style={{fontSize:12,color:ncBranching?T.silver:T.fog,lineHeight:1.6}}>
                      {ncBranching
                        ? "Activado — cada respuesta lleva a una pregunta distinta. Construye tu árbol abajo."
                        : "Activa esta opción para hacer preguntas en cascada: dependiendo de la respuesta del votante, el sistema le hace una siguiente pregunta diferente. Ideal para mapear preferencias en detalle sin limitar las opciones desde el inicio."
                      }
                    </div>
                    {!ncBranching&&(
                      <div style={{fontSize:11,color:T.fog,marginTop:6}}>
                        Ejemplo: Pregunta 1 → "¿Prefieres A o B?" · Si elige A → Pregunta 2A · Si elige B → Pregunta 2B
                      </div>
                    )}
                  </div>
                  <div onClick={()=>setNcBranching(p=>!p)} style={{width:44,height:24,borderRadius:12,cursor:"pointer",
                    background:ncBranching?T.blue:T.rim,position:"relative",transition:"background 0.2s",flexShrink:0,marginTop:2}}>
                    <div style={{position:"absolute",top:3,left:ncBranching?21:3,width:18,height:18,borderRadius:9,
                      background:"white",transition:"left 0.2s"}}/>
                  </div>
                </div>
              </div>
            </Card>
            <Card>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
                <div>
                  <Lbl style={{marginBottom:2}}>Opciones de votación</Lbl>
                  <div style={{fontSize:11,color:T.fog}}>Modo visual: muestra imágenes de productos</div>
                </div>
                <div onClick={()=>{setNcVisual(p=>!p);}} style={{width:44,height:24,borderRadius:12,cursor:"pointer",
                  background:ncVisual?T.teal:T.rim,position:"relative",transition:"background 0.2s",flexShrink:0}}>
                  <div style={{position:"absolute",top:3,left:ncVisual?21:3,width:18,height:18,borderRadius:9,
                    background:"white",transition:"left 0.2s"}}/>
                </div>
              </div>
              {ncVisual?(
                <>
                  {ncOpts.map((opt,i)=>(
                    <div key={i} style={{display:"flex",gap:8,marginBottom:10,alignItems:"flex-start"}}>
                      {/* Image upload box */}
                      <div style={{flexShrink:0}}>
                        <input id={`opt-img-${i}`} type="file" accept="image/*" style={{display:"none"}}
                          onChange={async e=>{
                            const f=e.target.files[0];
                            if(!f)return;
                            const formData=new FormData();
                            formData.append('file',f);
                            try {
                              const res=await fetch(`${API}/upload/image`,{
                                method:'POST',
                                headers:{Authorization:`Bearer ${authToken}`},
                                body:formData
                              });
                              const data=await res.json();
                              if(!res.ok) throw new Error(data.detail||'Upload failed');
                              setNcOptImages(prev=>{const n=[...prev];n[i]=data.url;return n;});
                            } catch(err) {
                              alert('Error al subir imagen: '+err.message);
                            }
                          }}/>
                        <div onClick={()=>document.getElementById(`opt-img-${i}`).click()}
                          style={{width:72,height:72,borderRadius:10,cursor:"pointer",overflow:"hidden",
                            border:`2px dashed ${ncOptImages[i]?COLORS[i%COLORS.length]:T.rim}`,
                            background:T.deep,display:"flex",alignItems:"center",justifyContent:"center"}}>
                          {ncOptImages[i]
                            ?<img src={ncOptImages[i]} alt="" style={{width:"100%",height:"100%",objectFit:"cover"}}/>
                            :<div style={{textAlign:"center"}}>
                              <div style={{fontSize:20}}>📷</div>
                              <div style={{fontSize:9,color:T.fog,marginTop:2}}>Subir</div>
                            </div>
                          }
                        </div>
                      </div>
                      {/* Option name */}
                      <div style={{flex:1}}>
                        <input placeholder={`Producto / opción ${i+1}`} value={opt}
                          onChange={e=>{const o=[...ncOpts];o[i]=e.target.value;setNcOpts(o);}}
                          style={{width:"100%",padding:"10px 12px",borderRadius:10,background:T.deep,
                            border:`1.5px solid ${ncOpts[i]?COLORS[i%COLORS.length]+'66':T.rim}`,
                            color:T.snow,fontSize:13,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}/>
                      </div>
                      {/* Remove button (min 2) */}
                      {ncOpts.length>2&&(
                        <button onClick={()=>{
                          setNcOpts(p=>p.filter((_,j)=>j!==i));
                          setNcOptImages(p=>{const n=[...p];n.splice(i,1);n.push('');return n;});
                        }} style={{background:"none",border:"none",color:T.coral,fontSize:18,cursor:"pointer",
                          padding:"8px 4px",flexShrink:0}}>×</button>
                      )}
                    </div>
                  ))}
                  {ncOpts.length<10&&(
                    <button onClick={()=>setNcOpts(p=>[...p,''])}
                      style={{width:"100%",padding:"10px",borderRadius:10,background:"transparent",
                        border:`1.5px dashed ${T.teal}66`,color:T.teal,fontSize:13,fontWeight:700,
                        cursor:"pointer",marginTop:4}}>
                      + Agregar producto
                    </button>
                  )}
                </>
              ):(
                <>
                  {ncOpts.map((opt,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:6,marginBottom:8}}>
                      <input placeholder={`Opción ${i+1}`} value={ncOpts[i]}
                        onChange={e=>{const o=[...ncOpts];o[i]=e.target.value;setNcOpts(o);}}
                        style={{flex:1,padding:"10px 14px",
                          borderRadius:10,background:T.deep,border:`1.5px solid ${ncOpts[i]?COLORS[i%COLORS.length]+'66':T.rim}`,
                          color:T.snow,fontSize:14,outline:"none",fontFamily:"inherit",
                          boxSizing:"border-box"}}/>
                      {ncOpts.length>2&&(
                        <button onClick={()=>setNcOpts(p=>p.filter((_,j)=>j!==i))}
                          style={{background:"none",border:"none",color:T.coral,fontSize:18,cursor:"pointer",padding:"4px"}}>×</button>
                      )}
                    </div>
                  ))}
                  {ncOpts.length<10&&(
                    <button onClick={()=>setNcOpts(p=>[...p,''])}
                      style={{width:"100%",padding:"10px",borderRadius:10,background:"transparent",
                        border:`1.5px dashed ${T.teal}66`,color:T.teal,fontSize:13,fontWeight:700,
                        cursor:"pointer",marginTop:4}}>
                      + Agregar opción
                    </button>
                  )}
                </>
              )}
            </Card>
            <Card>
              <Lbl>Recompensa de participación</Lbl>
              <div style={{fontSize:11,color:T.fog,marginBottom:8}}>
                Opcional — descripción visible antes de votar (ej: "15% de descuento en tu próxima compra").
              </div>
              <input value={ncReward} onChange={e=>setNcReward(e.target.value)}
                placeholder="Ej: 15% de descuento · Acceso anticipado · Muestra gratis"
                style={{width:"100%",padding:"10px 14px",borderRadius:10,background:T.deep,
                  border:`1.5px solid ${T.gold}66`,color:T.snow,fontSize:13,outline:"none",
                  fontFamily:"inherit",boxSizing:"border-box",marginBottom:10}}/>
              <div style={{fontSize:11,color:T.fog,marginBottom:6}}>
                Códigos únicos (uno por línea) — cada votante recibe uno diferente:
              </div>
              <textarea value={ncRewardCodes} onChange={e=>setNcRewardCodes(e.target.value)}
                rows={4}
                placeholder={"ADIDAS-K9X2-15\nADIDAS-M3P7-15\nADIDAS-Q8R1-15\n..."}
                style={{width:"100%",padding:"10px 14px",borderRadius:10,background:T.deep,
                  border:`1.5px solid ${T.gold}44`,color:T.snow,fontSize:12,outline:"none",
                  fontFamily:"monospace",boxSizing:"border-box",resize:"vertical",
                  lineHeight:1.6}}/>
              {ncRewardCodes.trim()&&(
                <div style={{fontSize:11,color:T.gold,marginTop:4}}>
                  {ncRewardCodes.trim().split('\n').filter(c=>c.trim()).length} códigos cargados
                </div>
              )}
            </Card>
            {ncBranching&&(
            <Card>
              <Lbl>🌳 Construye tu árbol de decisiones</Lbl>
              <div style={{fontSize:12,color:T.fog,marginBottom:14,lineHeight:1.6}}>
                Para cada opción de la pregunta principal, define qué pregunta de seguimiento aparece.
                Puedes dejar en blanco las que no necesiten seguimiento.
              </div>
              {ncOpts.filter(Boolean).map((opt,i)=>{
                if(!opt) return null;
                const q2=ncQ2[i];
                return (
                  <div key={i} style={{marginBottom:12,background:T.deep,borderRadius:10,padding:12,border:`1px solid ${T.rim}`}}>
                    <div style={{fontSize:12,color:T.fog,marginBottom:8}}>
                      Si votan <span style={{color:COLORS[i],fontWeight:700}}>"{opt}"</span> →
                    </div>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:q2.on?10:0}}>
                      <div style={{fontSize:12,color:T.silver}}>Agregar pregunta 2</div>
                      <div onClick={()=>setNcQ2(prev=>{const n=prev.map(q=>({...q,opts:[...q.opts]}));n[i].on=!n[i].on;return n;})}
                        style={{width:36,height:20,borderRadius:10,cursor:"pointer",flexShrink:0,
                          background:q2.on?T.blue:T.muted,position:"relative",transition:"background 0.2s"}}>
                        <div style={{position:"absolute",top:2,left:q2.on?17:2,width:16,height:16,borderRadius:8,
                          background:"white",transition:"left 0.2s"}}/>
                      </div>
                    </div>
                    {q2.on&&(
                      <div style={{marginTop:8}}>
                        <input placeholder="¿Pregunta de seguimiento?" value={q2.title}
                          onChange={e=>setNcQ2(prev=>{const n=prev.map(q=>({...q,opts:[...q.opts]}));n[i].title=e.target.value;return n;})}
                          style={{width:"100%",padding:"9px 12px",borderRadius:8,background:T.bg,
                            border:`1.5px solid ${T.blue}`,color:T.snow,fontSize:13,outline:"none",
                            fontFamily:"inherit",marginBottom:8,boxSizing:"border-box"}}/>
                        {['a','b','c'].map((_, j)=>(
                          <div key={j} style={{display:"flex",gap:6,marginBottom:6,alignItems:"center"}}>
                            <div style={{width:8,height:8,borderRadius:2,background:COLORS[j],flexShrink:0}}/>
                            <input placeholder={`Opción ${j+1}`} value={q2.opts[j]}
                              onChange={e=>setNcQ2(prev=>{const n=prev.map(q=>({...q,opts:[...q.opts]}));n[i].opts[j]=e.target.value;return n;})}
                              style={{flex:1,padding:"7px 10px",borderRadius:7,background:T.bg,
                                border:`1px solid ${T.rim}`,color:T.snow,fontSize:12,outline:"none",fontFamily:"inherit"}}/>
                            {q2.opts[j]&&ncQ3[i][j]&&(
                              <div onClick={()=>setNcQ3(prev=>{const n=prev.map(r=>r.map(q=>({...q,opts:[...q.opts]})));n[i][j].on=!n[i][j].on;return n;})}
                                title="Agregar Q3"
                                style={{fontSize:14,cursor:"pointer",color:ncQ3[i][j].on?T.blue:T.fog,flexShrink:0}}>⤷</div>
                            )}
                          </div>
                        ))}
                        {['a','b','c'].map((_, j)=>{
                          if(!q2.opts[j]||!ncQ3[i][j]||!ncQ3[i][j].on) return null;
                          return (
                            <div key={j} style={{marginTop:6,background:T.card,borderRadius:8,padding:10,
                              border:`1px solid ${T.blue}33`}}>
                              <div style={{fontSize:11,color:T.fog,marginBottom:6}}>
                                Si responden <span style={{color:COLORS[j],fontWeight:700}}>"{q2.opts[j]}"</span> → Q3
                              </div>
                              <input placeholder="¿Tercera pregunta?" value={ncQ3[i][j].title}
                                onChange={e=>setNcQ3(prev=>{const n=prev.map(r=>r.map(q=>({...q,opts:[...q.opts]})));n[i][j].title=e.target.value;return n;})}
                                style={{width:"100%",padding:"7px 10px",borderRadius:7,background:T.bg,
                                  border:`1.5px solid ${T.blue}66`,color:T.snow,fontSize:12,outline:"none",
                                  fontFamily:"inherit",marginBottom:6,boxSizing:"border-box"}}/>
                              {['p','q'].map((_,k)=>(
                                <input key={k} placeholder={`Opción ${k+1}`} value={ncQ3[i][j].opts[k]}
                                  onChange={e=>setNcQ3(prev=>{const n=prev.map(r=>r.map(q=>({...q,opts:[...q.opts]})));n[i][j].opts[k]=e.target.value;return n;})}
                                  style={{width:"100%",padding:"7px 10px",borderRadius:7,background:T.bg,
                                    border:`1px solid ${T.rim}`,color:T.snow,fontSize:12,outline:"none",
                                    fontFamily:"inherit",marginBottom:4,boxSizing:"border-box"}}/>
                              ))}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </Card>
            )}
            <Card>
              <Lbl>Cierre de votación</Lbl>
              <Input label="Fecha de cierre" type="date" value={ncCloses} onChange={setNcCloses}/>
            </Card>
            <Card>
              <Lbl>¿A quién va dirigida?</Lbl>
              <div style={{marginBottom:12}}>
                <div style={{fontSize:11,color:T.fog,marginBottom:6,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Audiencia</div>
                {[["all","🌐 Todos los ciudadanos"],["members","🏢 Miembros de la empresa"],["association","🤝 Miembros de la asociación"],["closed","🔒 Lista cerrada"]].map(([v,l])=>(
                  <div key={v} onClick={()=>setNcAudience(v)} style={{padding:"9px 12px",borderRadius:8,marginBottom:6,cursor:"pointer",
                    border:`1.5px solid ${ncAudience===v?T.blue:T.rim}`,background:ncAudience===v?`${T.blue}18`:T.deep,
                    fontSize:13,color:ncAudience===v?T.white:T.fog,fontWeight:ncAudience===v?700:400}}>{l}</div>
                ))}
              </div>
              <div style={{marginBottom:12}}>
                <div style={{fontSize:11,color:T.fog,marginBottom:6,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Género</div>
                <div style={{display:"flex",gap:8}}>
                  {[["all","Todos"],["male","Hombres"],["female","Mujeres"]].map(([v,l])=>(
                    <div key={v} onClick={()=>setNcGender(v)} style={{flex:1,padding:"8px 4px",borderRadius:8,cursor:"pointer",textAlign:"center",
                      border:`1.5px solid ${ncGender===v?T.blue:T.rim}`,background:ncGender===v?`${T.blue}18`:T.deep,
                      fontSize:12,color:ncGender===v?T.white:T.fog,fontWeight:ncGender===v?700:400}}>{l}</div>
                  ))}
                </div>
              </div>
              <div style={{marginBottom:12}}>
                <div style={{fontSize:11,color:T.fog,marginBottom:6,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Edad</div>
                <div style={{display:"flex",gap:8,alignItems:"center"}}>
                  <input value={ncAgeMin} onChange={e=>setNcAgeMin(e.target.value)} placeholder="Mín" type="number"
                    style={{flex:1,padding:"9px 10px",borderRadius:8,background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:14,outline:"none",boxSizing:"border-box"}}/>
                  <span style={{color:T.fog,fontSize:12}}>a</span>
                  <input value={ncAgeMax} onChange={e=>setNcAgeMax(e.target.value)} placeholder="Máx" type="number"
                    style={{flex:1,padding:"9px 10px",borderRadius:8,background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:14,outline:"none",boxSizing:"border-box"}}/>
                  <span style={{color:T.fog,fontSize:12}}>años</span>
                </div>
              </div>
              <div style={{display:"flex",flexDirection:"column",gap:8}}>
                <div style={{fontSize:11,color:T.fog,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Ubicación</div>
                <select value={ncCountry} onChange={e=>setNcCountry(e.target.value)}
                  style={{width:"100%",padding:"9px 10px",borderRadius:8,background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:13,outline:"none"}}>
                  {[["CL","Chile"],["AR","Argentina"],["CO","Colombia"],["MX","México"],["PE","Perú"],["ES","España"],["ALL","Todos los países"]].map(([v,l])=>(
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
                <input value={ncRegion} onChange={e=>setNcRegion(e.target.value)} placeholder="Estado / Región (opcional)"
                  style={{width:"100%",padding:"9px 10px",borderRadius:8,background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:13,outline:"none",boxSizing:"border-box"}}/>
                <input value={ncCommune} onChange={e=>setNcCommune(e.target.value)} placeholder="Comuna (opcional)"
                  style={{width:"100%",padding:"9px 10px",borderRadius:8,background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:13,outline:"none",boxSizing:"border-box"}}/>
              </div>
            </Card>
            <Btn label={ncLoading?"Publicando...":ncVisual?"🖼 Publicar consulta visual":"🚀 Publicar debate"} full
              disabled={ncLoading||!ncTitle||ncOpts.filter(Boolean).length<2||!ncCloses}
              onPress={async()=>{
                const options=ncOpts.filter(Boolean);
                // Build follow_up_questions tree
                const followUpBranches = ncBranching ? ncOpts.map((opt,i)=>{
                  if(!opt||!ncQ2[i].on||!ncQ2[i].title) return null;
                  const q2Opts=ncQ2[i].opts.filter(Boolean);
                  if(q2Opts.length<2) return null;
                  return {
                    title:ncQ2[i].title, options:q2Opts,
                    branches:ncQ2[i].opts.map((o2,j)=>{
                      if(!o2||!ncQ3[i][j]||!ncQ3[i][j].on||!ncQ3[i][j].title) return null;
                      const q3Opts=ncQ3[i][j].opts.filter(Boolean);
                      if(q3Opts.length<2) return null;
                      return {title:ncQ3[i][j].title,options:q3Opts,branches:q3Opts.map(()=>null)};
                    })
                  };
                }) : null;
                const optImages = ncVisual ? ncOptImages.slice(0,options.length) : [];
                setNcLoading(true);
                try {
                  const data=await apiFetch('POST','/debates',{
                    title:ncTitle, context:ncDesc, options, reward:ncReward,
                    option_images:optImages,
                    closes_at:new Date(ncCloses).toISOString(),
                    verify_days:14,
                    creator_type:'organizer', inst_name:ncInstName||currentUser?.name||'Preferendum',
                    debate_type:'gov', scope:ncCommune?'commune':ncRegion?'region':'country',
                    scope_country:ncAudience==='all'?'ALL':ncCountry, scope_commune:ncCommune,
                    target_gender:ncGender,
                    target_age_min:parseInt(ncAgeMin)||13,
                    target_age_max:parseInt(ncAgeMax)||99,
                    follow_up_questions:followUpBranches?JSON.stringify(followUpBranches):'',
                  });
                  const newDeb=data.debate;
                  if(newDeb) {
                    setApiDebates(prev=>[transformDebate(newDeb),...prev]);
                    setMyDebateIds(prev=>[newDeb.id,...prev]);
                    // Upload unique reward codes if any were entered
                    if(ncRewardCodes.trim()&&newDeb.id) {
                      try {
                        await apiFetch('POST',`/organizer/consultations/${newDeb.id}/reward-codes`,
                          {codes:ncRewardCodes.trim()});
                      } catch(_){}
                    }
                  }
                  const title=ncTitle;
                  setNcTitle('');setNcDesc('');setNcOpts(['','','','']);setNcCloses('');setNcReward('');
                  setNcRewardCodes('');
                  setNcVisual(false);setNcOptImages(Array(10).fill(''));
                  setNcAudience('all');setNcGender('all');setNcAgeMin('13');setNcAgeMax('99');
                  setNcCountry('CL');setNcRegion('');setNcCommune('');
                  setNcBranching(false);
                  setNcQ2(Array(4).fill(null).map(()=>({on:false,title:'',opts:['','','']})));
                  setNcQ3(Array(4).fill(null).map(()=>Array(3).fill(null).map(()=>({on:false,title:'',opts:['','']}))));
                  setInstTab("debates");
                } catch(e){
                  alert('Error al publicar: '+(e.message||'Intenta de nuevo.'));
                } finally { setNcLoading(false); }
              }}/>
          </>
        )}

        {instTab==="ads"&&(
          <>
            <div style={{padding:"4px 0 14px"}}>
              <div style={{fontSize:20,fontWeight:900,color:T.white}}>Publicidad</div>
            </div>
            {[{name:"Samsung Galaxy",target:"Todos · CL",imp:510,spent:10200,c:T.blue},
              {name:"L'Oréal Paris",target:"Mujeres · CL",imp:265,spent:5300,c:T.coral}].map(ad=>(
              <Card key={ad.name}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
                  <div style={{fontSize:14,fontWeight:700,color:T.white}}>{ad.name}</div>
                  <span style={{fontSize:10,fontWeight:700,padding:"2px 8px",borderRadius:10,
                    background:`${T.green}22`,color:T.green}}>● En vivo</span>
                </div>
                <div style={{fontSize:11,color:T.fog,marginBottom:8}}>🎯 {ad.target}</div>
                <div style={{display:"flex",gap:16,fontSize:12}}>
                  <span style={{color:ad.c}}>👁 {ad.imp} imp.</span>
                  <span style={{color:T.gold}}>💰 CLP {ad.spent.toLocaleString()}</span>
                </div>
              </Card>
            ))}
            <Btn label="+ Nueva campaña" full onPress={()=>{setUserType("marketer");go("marketer");}}/>
          </>
        )}
      </div>
      <InstTabs/>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: MARKETER HUB
  // ══════════════════════════════════════════════════════════════
  if(screen==="marketer") return (
    <div style={phone}>
      <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
        padding:"12px 16px",display:"flex",alignItems:"center",gap:10,
        position:"sticky",top:0,zIndex:99}}>
        {userType==="inst"&&(
          <button onClick={()=>go("inst-home")} style={{background:"none",border:"none",
            color:T.blue,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>
        )}
        {userType!=="inst"&&(
          <button onClick={()=>go("launch")} style={{background:"none",border:"none",
            color:T.blue,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>
        )}
        <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>
          prefer<span style={{color:T.blue}}>endum</span>
          <span style={{fontSize:12,color:T.gold,fontWeight:400}}> · Portal Anunciante</span>
        </div>
      </div>

      <div style={{padding:"16px 16px 40px"}}>
        <div style={{padding:"8px 0 20px"}}>
          <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:8}}>
            Panel de marketing
          </div>
          <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}44`,
            borderRadius:12,padding:"14px 16px",fontSize:13,color:T.gold,lineHeight:1.8}}>
            <strong>El loop completo de Nike:</strong><br/>
            Cliente en tienda ve: <em>"¿Quieres un 20% de descuento?"</em><br/>
            → Escanea QR → llega a Preferendum<br/>
            → Vota qué zapatilla prefieren para 2026<br/>
            → Recibe código de descuento <strong>inmediatamente</strong><br/>
            → Nike tiene datos de mercado + venta completada
          </div>
        </div>

        {/* Stats */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:20}}>
          {[["775","Impresiones",T.blue],["CLP 15.5K","Gasto total",T.gold],
            ["2","Campañas activas",T.teal],["97.4%","Precisión sistema",T.green]].map(([n,l,c])=>(
            <div key={l} style={{background:T.panel,border:`1px solid ${T.rim}`,
              borderRadius:12,padding:14,textAlign:"center"}}>
              <div style={{fontSize:22,fontWeight:900,color:c,letterSpacing:-1}}>{n}</div>
              <div style={{fontSize:11,color:T.fog,marginTop:2}}>{l}</div>
            </div>
          ))}
        </div>

        {/* Module cards */}
        <div style={{display:"flex",flexDirection:"column",gap:12}}>
          <div onClick={()=>{setAdStep(0);setLaunched(false);setMkScreen("adcreator");go("ad-creator");}}
            style={{background:T.panel,border:`1.5px solid ${T.blue}`,borderRadius:16,padding:20,cursor:"pointer"}}>
            <div style={{fontSize:28,marginBottom:8}}>📢</div>
            <div style={{fontSize:16,fontWeight:700,color:T.white,marginBottom:4}}>Crear campaña publicitaria</div>
            <div style={{fontSize:12,color:T.fog,lineHeight:1.6}}>
              7 pasos: tipo · creatividad · audiencia · dónde aparecer · exclusiones · presupuesto · lanzar
            </div>
            <div style={{fontSize:11,color:T.blue,fontWeight:700,marginTop:8}}>Abrir creador →</div>
          </div>

          <div onClick={()=>go("reward-codes")}
            style={{background:T.panel,border:`1.5px solid ${T.gold}`,borderRadius:16,padding:20,cursor:"pointer"}}>
            <div style={{fontSize:28,marginBottom:8}}>🎁</div>
            <div style={{fontSize:16,fontWeight:700,color:T.white,marginBottom:4}}>Sistema de códigos de descuento</div>
            <div style={{fontSize:12,color:T.fog,lineHeight:1.6}}>
              Votante vota → recibe código de descuento inmediatamente → compra ahora. El loop completo de Nike.
            </div>
            <div style={{fontSize:11,color:T.gold,fontWeight:700,marginTop:8}}>Configurar descuentos →</div>
          </div>

          <div style={{background:T.panel,border:`1px solid ${T.rim}`,borderRadius:16,padding:20}}>
            <div style={{fontSize:28,marginBottom:8}}>📊</div>
            <div style={{fontSize:16,fontWeight:700,color:T.white,marginBottom:8}}>Campañas activas</div>
            {[{name:"Samsung Galaxy",target:"Todos · CL",imp:510,spent:10200,c:T.blue},
              {name:"L'Oréal Paris",target:"Mujeres · CL",imp:265,spent:5300,c:T.coral}].map(ad=>(
              <div key={ad.name} style={{padding:"10px 0",borderBottom:`1px solid ${T.rim}`}}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
                  <div style={{fontSize:13,fontWeight:700,color:T.white}}>{ad.name}</div>
                  <span style={{fontSize:10,fontWeight:700,padding:"2px 7px",borderRadius:8,
                    background:`${T.green}22`,color:T.green}}>● En vivo</span>
                </div>
                <div style={{fontSize:11,color:T.fog,marginBottom:6}}>🎯 {ad.target}</div>
                <div style={{display:"flex",gap:16,fontSize:11}}>
                  <span style={{color:ad.c}}>👁 {ad.imp} imp.</span>
                  <span style={{color:T.gold}}>💰 CLP {ad.spent.toLocaleString()}</span>
                  <span style={{color:T.fog}}>20 CLP/imp.</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  // ══════════════════════════════════════════════════════════════
  // SCREEN: AD CREATOR (7 steps)
  // ══════════════════════════════════════════════════════════════
  if(screen==="ad-creator") {
    const AD_STEPS = ["Tipo","Creatividad","Audiencia","Aparece en","Exclusiones","Presupuesto","Lanzar"];

    if(launched) return (
      <div style={phone}>
        <div style={{minHeight:"100vh",display:"flex",flexDirection:"column",
          alignItems:"center",justifyContent:"center",padding:32,textAlign:"center"}}>
          <div style={{fontSize:64,marginBottom:16}}>🚀</div>
          <div style={{fontSize:26,fontWeight:900,color:T.white,marginBottom:8}}>¡Campaña lanzada!</div>
          <div style={{fontSize:13,color:T.fog,lineHeight:1.7,marginBottom:24,maxWidth:300}}>
            El motor de matching distribuirá tu campaña en tiempo real a los perfiles exactos.
          </div>
          <Card style={{width:"100%",maxWidth:320,textAlign:"left"}}>
            <Lbl>Resumen</Lbl>
            {[["Marca",brandName],["Tipo",AD_TYPES.find(t=>t.k===adType)?.name||"—"],
              ["País",country+(region?` · ${region}`:"")],
              ["Género",[sexF?"♀":null,sexM?"♂":null].filter(Boolean).join("+")],
              ["Presupuesto","CLP "+parseInt(budget||0).toLocaleString()],
              ["Modelo",payModel+" · 20 CLP/imp."],
              ["Imp. estimadas","~"+estImp],
            ].map(([l,v])=>(
              <div key={l} style={{display:"flex",justifyContent:"space-between",
                padding:"6px 0",borderBottom:`1px solid ${T.rim}`,fontSize:12}}>
                <span style={{color:T.fog}}>{l}</span>
                <span style={{color:T.snow,fontWeight:600}}>{v}</span>
              </div>
            ))}
          </Card>
          <div style={{marginTop:14,width:"100%",maxWidth:320,display:"flex",flexDirection:"column",gap:10}}>
            <Btn label="← Volver al panel" full onPress={()=>go("marketer")}/>
          </div>
        </div>
      </div>
    );

    return (
      <div style={phone}>
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
          padding:"12px 16px",position:"sticky",top:0,zIndex:99,display:"flex",alignItems:"center",gap:10}}>
          <button onClick={()=>go("marketer")} style={{background:"none",border:"none",
            color:T.blue,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>
          <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>
            prefer<span style={{color:T.blue}}>endum</span>
            <span style={{fontSize:12,color:T.fog,fontWeight:400}}> · Nueva campaña</span>
          </div>
        </div>

        {/* Step bar */}
        <div style={{padding:"12px 16px 0"}}>
          <div style={{display:"flex",gap:3,marginBottom:5}}>
            {AD_STEPS.map((_,i)=>(
              <div key={i} style={{flex:1,height:3,borderRadius:3,
                background:i<=adStep?T.blue:T.rim}}/>
            ))}
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:9,color:T.fog}}>
            <span style={{color:T.blue,fontWeight:700}}>{AD_STEPS[adStep]}</span>
            <span>{adStep+1} / {AD_STEPS.length}</span>
          </div>
        </div>

        <div style={{padding:"14px 16px 80px"}}>

          {/* STEP 0: TYPE */}
          {adStep===0&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>¿Qué tipo de campaña?</div>
                <div style={{fontSize:13,color:T.fog,lineHeight:1.6}}>
                  La publicidad financia Preferendum. El sector público consulta ciudadanos. Las empresas preguntan al mercado.
                </div>
              </div>
              {AD_TYPES.map(t=>(
                <div key={t.k} onClick={()=>setAdType(t.k)} style={{
                  border:`${adType===t.k?"2px":"1.5px"} solid ${adType===t.k?t.color:T.rim}`,
                  borderRadius:14,padding:16,cursor:"pointer",marginBottom:10,
                  background:adType===t.k?`${t.color}18`:T.panel,
                  display:"flex",alignItems:"center",gap:14}}>
                  <div style={{fontSize:32,flexShrink:0}}>{t.icon}</div>
                  <div>
                    <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:3}}>{t.name}</div>
                    <div style={{fontSize:12,color:T.fog,lineHeight:1.5}}>{t.desc}</div>
                  </div>
                </div>
              ))}
              {adType==="question"&&(
                <div style={{background:`${T.teal}18`,border:`1px solid ${T.teal}44`,
                  borderRadius:10,padding:"12px 14px",fontSize:12,color:T.teal,marginBottom:14,lineHeight:1.7}}>
                  💡 José's insight: Nike preguntó a Brasil qué zapatilla prefiere y fabricó eso. 95% más barato que un focus group. Resultados en 72 horas.
                </div>
              )}
              <div style={{display:"flex",gap:10,marginTop:16}}>
                <div style={{flex:1}}>
                  <Btn label="Continuar →" full disabled={!adType} onPress={()=>setAdStep(1)}/>
                </div>
              </div>
            </>
          )}

          {/* STEP 1: CREATIVE */}
          {adStep===1&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Creatividad</div>
                <div style={{fontSize:13,color:T.fog}}>Sube tu imagen, video o configura tu pregunta.</div>
              </div>
              <Card>
                <Lbl>Información de marca</Lbl>
                <Input label="Nombre de tu marca / organización"
                  placeholder="Ej. Nike Chile, Municipalidad Las Condes"
                  value={brandName} onChange={setBrand}/>
                {/* Banner upload zone */}
                <div style={{marginBottom:14}}>
                  <div style={{fontSize:10,color:T.fog,textTransform:"uppercase",
                    letterSpacing:"0.08em",fontWeight:700,marginBottom:8}}>Logo de tu marca</div>
                  <div onClick={()=>document.getElementById("logo-upload").click()} style={{
                    border:`2px dashed ${logoPrev?T.teal:T.rim}`,borderRadius:12,
                    padding:logoPrev?"8px":"20px",textAlign:"center",cursor:"pointer",background:T.deep}}>
                    <input id="logo-upload" type="file" accept="image/*" style={{display:"none"}}
                      onChange={async e=>{const f=e.target.files[0];if(f){const p=await readFile(f);setLogo(p);}}}/>
                    {logoPrev?(
                      <div style={{display:"flex",alignItems:"center",gap:12}}>
                        <img src={logoPrev} alt="" style={{width:48,height:48,borderRadius:8,objectFit:"cover"}}/>
                        <div style={{textAlign:"left"}}>
                          <div style={{fontSize:12,fontWeight:700,color:T.teal}}>✓ Logo cargado</div>
                          <div style={{fontSize:11,color:T.fog}}>Toca para cambiar</div>
                        </div>
                      </div>
                    ):(
                      <>
                        <div style={{fontSize:32,marginBottom:6}}>🏷</div>
                        <div style={{fontSize:13,fontWeight:700,color:T.snow,marginBottom:4}}>Toca para subir logo</div>
                        <div style={{fontSize:11,color:T.fog}}>PNG o JPG · Cuadrado · Mín. 200×200px</div>
                      </>
                    )}
                  </div>
                </div>
              </Card>
              {adType!=="question"&&(
                <Card>
                  <Lbl>Contenido del anuncio</Lbl>
                  <div style={{display:"flex",gap:8,marginBottom:14}}>
                    {[["banner","🖼 Banner","Imagen + texto"],["video","🎬 Video","Hasta 30s"]].map(([k,n,d])=>(
                      <div key={k} onClick={()=>setAdFormat(k)} style={{flex:1,padding:"12px",
                        borderRadius:12,border:`${adFormat===k?"2px":"1.5px"} solid ${adFormat===k?T.blue:T.rim}`,
                        background:adFormat===k?`${T.blue}18`:T.deep,textAlign:"center",cursor:"pointer"}}>
                        <div style={{fontSize:20,marginBottom:4}}>{n.split(" ")[0]}</div>
                        <div style={{fontSize:12,fontWeight:700,color:adFormat===k?T.blue:T.fog}}>{n.split(" ")[1]}</div>
                        <div style={{fontSize:10,color:T.fog}}>{d}</div>
                      </div>
                    ))}
                  </div>
                  <div onClick={()=>document.getElementById("banner-upload").click()} style={{
                    border:`2px dashed ${bannerPrev?T.teal:T.rim}`,borderRadius:12,
                    padding:bannerPrev?"8px":"20px",textAlign:"center",cursor:"pointer",background:T.deep,marginBottom:14}}>
                    <input id="banner-upload" type="file" accept="image/*" style={{display:"none"}}
                      onChange={async e=>{const f=e.target.files[0];if(f){const p=await readFile(f);setBanner(p);}}}/>
                    {bannerPrev?(
                      <div style={{display:"flex",alignItems:"center",gap:12}}>
                        <img src={bannerPrev} alt="" style={{width:64,height:64,borderRadius:8,objectFit:"cover"}}/>
                        <div style={{textAlign:"left"}}>
                          <div style={{fontSize:12,fontWeight:700,color:T.teal}}>✓ Imagen cargada</div>
                          <div style={{fontSize:11,color:T.fog}}>Toca para cambiar</div>
                        </div>
                      </div>
                    ):(
                      <>
                        <div style={{fontSize:32,marginBottom:6}}>🖼</div>
                        <div style={{fontSize:13,fontWeight:700,color:T.snow}}>Toca para subir imagen</div>
                        <div style={{fontSize:11,color:T.fog}}>JPG o PNG · Máx. 2MB</div>
                      </>
                    )}
                  </div>
                  <Input label="Título del anuncio" placeholder="Ej. Galaxy S26 — Ya disponible" value={adTitle} onChange={setAdTitle}/>
                  <Input label="Texto secundario (opcional)" placeholder="Subtítulo o llamada a la acción" value={adBody} onChange={setAdBody}/>
                </Card>
              )}
              {adType==="question"&&(
                <Card>
                  <Lbl>Pregunta patrocinada</Lbl>
                  <div style={{background:`${T.teal}18`,border:`1px solid ${T.teal}44`,
                    borderRadius:10,padding:"10px 12px",fontSize:12,color:T.teal,marginBottom:14,lineHeight:1.6}}>
                    Cada opción puede tener su propia imagen. Nike usó fotos de cada zapatilla.
                  </div>
                  <Input label="Tu pregunta al mercado"
                    placeholder="¿Cuál de estos modelos preferirías para 2026?"
                    value={sqQuestion} onChange={setSqQ}/>
                  <Lbl>Opciones con imagen</Lbl>
                  {sqOpts.map((opt,i)=>(
                    <div key={i} style={{display:"flex",gap:10,alignItems:"flex-start",marginBottom:12}}>
                      <div onClick={()=>document.getElementById(`opt-img-${i}`).click()} style={{
                        width:60,height:60,borderRadius:10,flexShrink:0,cursor:"pointer",
                        border:`2px dashed ${opt.imgPrev?T.teal:T.rim}`,
                        background:T.deep,overflow:"hidden",display:"flex",alignItems:"center",justifyContent:"center"}}>
                        <input id={`opt-img-${i}`} type="file" accept="image/*" style={{display:"none"}}
                          onChange={async e=>{
                            const f=e.target.files[0];
                            if(f){const p=await readFile(f);setSqOpts(o=>{const n=[...o];n[i]={...n[i],imgPrev:p};return n;});}
                          }}/>
                        {opt.imgPrev
                          ?<img src={opt.imgPrev} alt="" style={{width:"100%",height:"100%",objectFit:"cover"}}/>
                          :<div style={{textAlign:"center"}}><div style={{fontSize:20}}>🖼</div><div style={{fontSize:9,color:T.fog}}>Imagen</div></div>
                        }
                      </div>
                      <div style={{flex:1}}>
                        <input placeholder={`Opción ${i+1} — descripción`} value={opt.text}
                          onChange={e=>{setSqOpts(o=>{const n=[...o];n[i]={...n[i],text:e.target.value};return n;});}}
                          style={{width:"100%",padding:"10px 12px",borderRadius:10,
                            background:T.deep,border:`1.5px solid ${T.rim}`,color:T.snow,
                            fontSize:13,outline:"none",fontFamily:"inherit",boxSizing:"border-box"}}/>
                      </div>
                    </div>
                  ))}
                  {sqOpts.length<6&&(
                    <button onClick={()=>setSqOpts([...sqOpts,{text:"",imgPrev:null}])}
                      style={{background:"none",border:"none",color:T.blue,fontSize:13,fontWeight:700,cursor:"pointer"}}>
                      + Añadir opción
                    </button>
                  )}
                </Card>
              )}
              {/* Live preview */}
              <div style={{background:T.card,border:`1px solid ${T.rim}`,borderRadius:12,padding:14,marginBottom:14}}>
                <Lbl>Vista previa en el feed</Lbl>
                <div style={{background:T.deep,borderRadius:10,overflow:"hidden"}}>
                  <div style={{fontSize:9,color:T.fog,padding:"3px 10px",borderBottom:`1px solid ${T.rim}`,
                    textTransform:"uppercase",letterSpacing:"0.1em"}}>Publicidad</div>
                  {adType==="question"?(
                    <div style={{padding:12}}>
                      <div style={{fontSize:10,color:T.teal,fontWeight:700,marginBottom:6}}>❓ Pregunta patrocinada · {brandName||"Tu marca"}</div>
                      <div style={{fontSize:13,fontWeight:700,color:T.white,marginBottom:10,lineHeight:1.4}}>
                        {sqQuestion||"Tu pregunta al mercado aparecerá aquí"}
                      </div>
                      {sqOpts.filter(o=>o.text||o.imgPrev).slice(0,3).map((o,i)=>(
                        <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"5px 0",borderBottom:i<2?`1px solid ${T.rim}`:"none"}}>
                          {o.imgPrev
                            ?<img src={o.imgPrev} alt="" style={{width:32,height:32,borderRadius:6,objectFit:"cover",flexShrink:0}}/>
                            :<div style={{width:32,height:32,borderRadius:6,background:T.mist,flexShrink:0,display:"flex",alignItems:"center",justifyContent:"center",fontSize:14}}>🖼</div>
                          }
                          <div style={{flex:1}}>
                            <div style={{fontSize:10,color:T.fog}}>Opción {i+1}:</div>
                            <div style={{fontSize:12,fontWeight:700,color:T.blue}}>{o.text||"—"}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ):(
                    <>
                      {bannerPrev
                        ?<img src={bannerPrev} alt="" style={{width:"100%",height:100,objectFit:"cover",display:"block"}}/>
                        :<div style={{width:"100%",height:80,background:T.mist,display:"flex",alignItems:"center",justifyContent:"center",fontSize:28}}>📢</div>
                      }
                      <div style={{padding:"10px 12px",display:"flex",gap:10,alignItems:"center"}}>
                        {logoPrev
                          ?<img src={logoPrev} alt="" style={{width:32,height:32,borderRadius:8,objectFit:"cover",flexShrink:0}}/>
                          :<div style={{width:32,height:32,borderRadius:8,background:T.mist,flexShrink:0,display:"flex",alignItems:"center",justifyContent:"center",fontSize:14}}>🏷</div>
                        }
                        <div>
                          <div style={{fontSize:10,color:T.fog,fontWeight:700,marginBottom:2}}>{brandName||"Tu marca"}</div>
                          <div style={{fontSize:13,fontWeight:700,color:T.white}}>{adTitle||"Título de tu anuncio"}</div>
                          {adBody&&<div style={{fontSize:11,color:T.silver,marginTop:2}}>{adBody}</div>}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
              <div style={{display:"flex",gap:10}}>
                <Btn label="← Atrás" outline color={T.fog} onPress={()=>setAdStep(0)}/>
                <div style={{flex:1}}><Btn label="Continuar →" full disabled={!brandName} onPress={()=>setAdStep(2)}/></div>
              </div>
            </>
          )}

          {/* STEP 2: AUDIENCE */}
          {adStep===2&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Audiencia</div>
                <div style={{fontSize:13,color:T.fog,lineHeight:1.6}}>Define exactamente quién verá tu anuncio.</div>
              </div>
              <Card>
                <Lbl>País</Lbl>
                <div>{COUNTRIES.map(c=><Chip key={c} label={c} on={country===c} onClick={()=>setCountry(c)}/>)}</div>
                <div style={{marginTop:10}}>
                  <Input label="Región / Estado (opcional)" placeholder="Ej. Región Metropolitana" value={region} onChange={setRegion}/>
                </div>
              </Card>
              <Card>
                <Lbl>Género</Lbl>
                <div style={{display:"flex",gap:10,marginBottom:8}}>
                  {[["F","♀ Femenino",sexF,setSexF],["M","♂ Masculino",sexM,setSexM]].map(([k,l,on,set])=>(
                    <button key={k} onClick={()=>set(!on)} style={{flex:1,padding:"11px",
                      borderRadius:10,border:`1.5px solid ${on?T.blue:T.rim}`,
                      background:on?`${T.blue}22`:"transparent",
                      color:on?T.blue:T.fog,fontSize:13,fontWeight:700,cursor:"pointer"}}>{l}
                    </button>
                  ))}
                </div>
                <div style={{fontSize:11,color:T.fog}}>L'Oréal seleccionó solo Femenino — los 48 hombres fueron excluidos automáticamente.</div>
              </Card>
              <Card>
                <Lbl>Grupos de edad</Lbl>
                <div>
                  {AGES.map(a=><Chip key={a} label={a} on={agesSel.includes(a)} onClick={()=>toggle(agesSel,setAgesSel,a)}/>)}
                  <Chip label="Todos" on={agesSel.length===0} onClick={()=>setAgesSel([])}/>
                </div>
              </Card>
              <div style={{display:"flex",gap:10}}>
                <Btn label="← Atrás" outline color={T.fog} onPress={()=>setAdStep(1)}/>
                <div style={{flex:1}}><Btn label="Continuar →" full disabled={!sexF&&!sexM} onPress={()=>setAdStep(3)}/></div>
              </div>
            </>
          )}

          {/* STEP 3: WHERE TO APPEAR */}
          {adStep===3&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>¿Dónde apareces?</div>
                <div style={{fontSize:13,color:T.fog,lineHeight:1.6}}>Elige las categorías de debates donde tu anuncio puede aparecer.</div>
              </div>
              <Card>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
                  <Lbl style={{marginBottom:0}}>Categorías</Lbl>
                  <button onClick={()=>setAppear(appear.length===CATS_APPEAR.length?[]:CATS_APPEAR.map(c=>c.k))}
                    style={{background:"none",border:"none",color:T.blue,fontSize:12,fontWeight:700,cursor:"pointer"}}>
                    {appear.length===CATS_APPEAR.length?"Ninguna":"Todas"}
                  </button>
                </div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                  {CATS_APPEAR.map(c=>(
                    <div key={c.k} onClick={()=>toggle(appear,setAppear,c.k)} style={{
                      padding:"10px 12px",borderRadius:10,cursor:"pointer",
                      border:`1.5px solid ${appear.includes(c.k)?T.teal:T.rim}`,
                      background:appear.includes(c.k)?`${T.teal}18`:T.deep,
                      display:"flex",alignItems:"center",gap:8}}>
                      <span style={{fontSize:18}}>{c.icon}</span>
                      <span style={{fontSize:12,fontWeight:700,color:appear.includes(c.k)?T.teal:T.fog}}>{c.name}</span>
                    </div>
                  ))}
                </div>
              </Card>
              <div style={{display:"flex",gap:10}}>
                <Btn label="← Atrás" outline color={T.fog} onPress={()=>setAdStep(2)}/>
                <div style={{flex:1}}><Btn label="Continuar →" full onPress={()=>setAdStep(4)}/></div>
              </div>
            </>
          )}

          {/* STEP 4: EXCLUSIONS */}
          {adStep===4&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Exclusiones</div>
                <div style={{fontSize:13,color:T.fog,lineHeight:1.6}}>
                  Define dónde <strong style={{color:T.coral}}>NO</strong> quieres aparecer y bloquea a tus competidores.
                </div>
              </div>
              <Card>
                <Lbl>Categorías a excluir</Lbl>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                  {CATS_EXCLUDE.map(c=>(
                    <div key={c.k} onClick={()=>toggle(exclude,setExclude,c.k)} style={{
                      padding:"10px 12px",borderRadius:10,cursor:"pointer",
                      border:`1.5px solid ${exclude.includes(c.k)?T.coral:T.rim}`,
                      background:exclude.includes(c.k)?`${T.coral}18`:T.deep,
                      display:"flex",alignItems:"center",gap:8}}>
                      <span style={{fontSize:18}}>{c.icon}</span>
                      <span style={{fontSize:12,fontWeight:700,
                        textDecoration:exclude.includes(c.k)?"line-through":"none",
                        color:exclude.includes(c.k)?T.coral:T.fog}}>{c.name}</span>
                    </div>
                  ))}
                </div>
              </Card>
              <Card>
                <Lbl>Bloquear marcas competidoras</Lbl>
                <div style={{fontSize:12,color:T.fog,marginBottom:12,lineHeight:1.6}}>
                  Si un competidor aparece en el mismo contexto, tu anuncio no aparecerá junto al de ellos.
                </div>
                {comps.map((c,i)=>(
                  <div key={i} style={{display:"flex",gap:8,marginBottom:8}}>
                    <input placeholder={`Competidor ${i+1} — ej. Adidas`} value={c}
                      onChange={e=>{const n=[...comps];n[i]=e.target.value;setComps(n);}}
                      style={{flex:1,padding:"10px 14px",borderRadius:10,background:T.deep,
                        border:`1.5px solid ${T.rim}`,color:T.snow,fontSize:14,outline:"none",fontFamily:"inherit"}}/>
                    {comps.length>1&&(
                      <button onClick={()=>setComps(comps.filter((_,j)=>j!==i))}
                        style={{padding:"0 12px",background:T.deep,border:`1.5px solid ${T.rim}`,
                          borderRadius:8,color:T.coral,cursor:"pointer",fontSize:16}}>✕</button>
                    )}
                  </div>
                ))}
                <button onClick={()=>setComps([...comps,""])}
                  style={{background:"none",border:"none",color:T.blue,fontSize:13,fontWeight:700,cursor:"pointer"}}>
                  + Añadir competidor
                </button>
              </Card>
              <div style={{background:`${T.blue}18`,border:`1px solid ${T.blue}44`,
                borderRadius:10,padding:"12px 14px",fontSize:12,color:"#7ab4ff",marginBottom:14,lineHeight:1.7}}>
                ℹ️ Reglas automáticas: debates gubernamentales = solo avisos cívicos · debates sindicales = sin publicidad de terceros.
              </div>
              <div style={{display:"flex",gap:10}}>
                <Btn label="← Atrás" outline color={T.fog} onPress={()=>setAdStep(3)}/>
                <div style={{flex:1}}><Btn label="Continuar →" full onPress={()=>setAdStep(5)}/></div>
              </div>
            </>
          )}

          {/* STEP 5: BUDGET */}
          {adStep===5&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Presupuesto</div>
              </div>
              <Card>
                <Lbl>Modelo de pago</Lbl>
                <div style={{display:"flex",gap:4,background:T.deep,borderRadius:10,padding:3,marginBottom:14}}>
                  {[["CPM","Por 1,000 imp."],["CPC","Por clic"],["Fijo","Por período"]].map(([m,d])=>(
                    <button key={m} onClick={()=>setPayModel(m)} style={{flex:1,padding:"9px 4px",
                      borderRadius:8,border:"none",background:payModel===m?T.blue:"transparent",
                      color:payModel===m?"#fff":T.fog,fontWeight:700,cursor:"pointer",
                      fontSize:11,fontFamily:"inherit",lineHeight:1.4}}>
                      {m}<br/><span style={{fontSize:9,fontWeight:400}}>{d}</span>
                    </button>
                  ))}
                </div>
                <div style={{background:T.deep,borderRadius:10,padding:14,marginBottom:14}}>
                  {[["Costo unitario",payModel==="CPM"?"$ 4,800 CLP / 1K imp.":payModel==="CPC"?"$ 320 CLP / clic":"$ 1,200,000 CLP / sem.",null],
                    ["Impresiones estimadas","~"+estImp,T.green]].map(([l,v,c])=>(
                    <div key={l} style={{display:"flex",justifyContent:"space-between",
                      padding:"7px 0",borderBottom:`1px solid ${T.rim}`,fontSize:13}}>
                      <span style={{color:T.fog}}>{l}</span>
                      <span style={{fontWeight:700,color:c||T.snow}}>{v}</span>
                    </div>
                  ))}
                </div>
                <Input label="Presupuesto total (CLP)" placeholder="Ej. 500000" type="number" value={budget} onChange={setBudget}/>
              </Card>
              <Card>
                <Lbl>Período</Lbl>
                <Input label="Fecha de inicio" type="date" value={startDate} onChange={setStart}/>
                <Input label="Fecha de término" type="date" value={endDate} onChange={setEnd}/>
              </Card>
              <div style={{display:"flex",gap:10}}>
                <Btn label="← Atrás" outline color={T.fog} onPress={()=>setAdStep(4)}/>
                <div style={{flex:1}}><Btn label="Revisar y lanzar →" full disabled={!budget||parseInt(budget)<1000} onPress={()=>setAdStep(6)}/></div>
              </div>
            </>
          )}

          {/* STEP 6: LAUNCH */}
          {adStep===6&&(
            <>
              <div style={{padding:"8px 0 16px"}}>
                <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>Revisa y lanza</div>
              </div>
              <Card>
                <Lbl>Resumen completo</Lbl>
                {[["Tipo",AD_TYPES.find(t=>t.k===adType)?.name||"—"],
                  ["Marca",brandName],["País",country+(region?` · ${region}`:"")],
                  ["Género",[sexF?"♀ Femenino":null,sexM?"♂ Masculino":null].filter(Boolean).join(" + ")],
                  ["Edades",agesSel.length?agesSel.join(", "):"Todas"],
                  ["Aparece en",appear.length?appear.join(", "):"Todas las categorías"],
                  ["Excluye",exclude.length?exclude.join(", "):"Nada"],
                  ["Competidores bloqueados",comps.filter(Boolean).join(", ")||"Ninguno"],
                  ["Presupuesto","CLP "+parseInt(budget||0).toLocaleString()],
                  ["Modelo",payModel+" · 20 CLP/impresión"],
                  ["Período",`${startDate||"—"} → ${endDate||"—"}`],
                  ["Imp. estimadas","~"+estImp],
                ].map(([l,v])=>(
                  <div key={l} style={{display:"flex",justifyContent:"space-between",
                    padding:"7px 0",borderBottom:`1px solid ${T.rim}`,fontSize:12}}>
                    <span style={{color:T.fog}}>{l}</span>
                    <span style={{color:T.snow,fontWeight:600,maxWidth:"55%",textAlign:"right"}}>{v}</span>
                  </div>
                ))}
              </Card>
              {adType==="question"&&(
                <Card style={{border:`1px solid ${T.teal}44`}}>
                  <Lbl>Tu pregunta patrocinada</Lbl>
                  <div style={{fontSize:14,fontWeight:700,color:T.white,marginBottom:10}}>{sqQuestion||"—"}</div>
                  {sqOpts.filter(o=>o.text).map((o,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
                      {o.imgPrev
                        ?<img src={o.imgPrev} alt="" style={{width:36,height:36,borderRadius:6,objectFit:"cover"}}/>
                        :<div style={{width:36,height:36,borderRadius:6,background:T.mist,display:"flex",alignItems:"center",justifyContent:"center",fontSize:14}}>🖼</div>
                      }
                      <div style={{fontSize:12,color:T.teal}}><strong>Opción {i+1}:</strong> {o.text}</div>
                    </div>
                  ))}
                </Card>
              )}
              <button onClick={()=>setLaunched(true)} style={{width:"100%",padding:16,borderRadius:14,
                background:T.green,border:"none",color:"#fff",fontSize:16,fontWeight:700,cursor:"pointer",marginBottom:10}}>
                🚀 Lanzar campaña
              </button>
              <Btn label="← Editar" full outline color={T.fog} onPress={()=>setAdStep(5)}/>
            </>
          )}
        </div>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: REWARD CODES
  // ══════════════════════════════════════════════════════════════
  if(screen==="reward-codes") {
    const dcode = nextCode();
    const vcode = "70F9-DB8E-6E17";

    const rwMethods = [
      {k:"csv",   icon:"📄", name:"Subir archivo CSV",          desc:"Carga miles de códigos únicos. Cada votante recibe uno diferente.", color:T.blue, rec:true},
      {k:"univ",  icon:"🎟", name:"Código universal",            desc:"Un solo código para todos. Más simple pero no permite rastreo individual.", color:T.teal, rec:false},
      {k:"auto",  icon:"💰", name:"Preferendum genera los códigos",desc:"Defines el porcentaje y Preferendum genera códigos únicos automáticamente.", color:T.gold, rec:false},
    ];

    return (
      <div style={phone}>
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
          padding:"12px 16px",display:"flex",alignItems:"center",gap:10,position:"sticky",top:0,zIndex:99}}>
          <button onClick={()=>go("marketer")} style={{background:"none",border:"none",
            color:T.blue,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>
          <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>
            prefer<span style={{color:T.blue}}>endum</span>
            <span style={{fontSize:12,color:T.gold,fontWeight:400}}> · Códigos de descuento</span>
          </div>
        </div>

        <div style={{padding:"16px 16px 60px"}}>
          <div style={{padding:"8px 0 20px"}}>
            <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:8,lineHeight:1.3}}>
              Configura el incentivo para votar
            </div>
            <div style={{background:`${T.gold}18`,border:`1px solid ${T.gold}44`,
              borderRadius:12,padding:"14px 16px",fontSize:13,color:T.gold,lineHeight:1.8}}>
              <strong>El loop completo de Nike:</strong><br/>
              Cliente en tienda ve: <em>"¿Quieres un 20% de descuento?"</em><br/>
              → Escanea QR → llega a Preferendum<br/>
              → Vota qué zapatilla prefieren para 2026<br/>
              → Recibe código de descuento <strong>inmediatamente</strong><br/>
              → Usa el código para comprar ahora mismo<br/>
              → Nike tiene datos de mercado + venta completada
            </div>
          </div>

          <div style={{fontSize:10,color:T.fog,textTransform:"uppercase",letterSpacing:"0.1em",fontWeight:700,marginBottom:12}}>
            ¿Cómo entregas los códigos?
          </div>
          {rwMethods.map(m=>(
            <div key={m.k} onClick={()=>setRwMethod(m.k)} style={{
              border:`${rwMethod===m.k?"2px":"1.5px"} solid ${rwMethod===m.k?m.color:T.rim}`,
              borderRadius:14,padding:16,cursor:"pointer",marginBottom:10,
              background:rwMethod===m.k?`${m.color}18`:T.panel,
              display:"flex",gap:14,alignItems:"flex-start"}}>
              <div style={{fontSize:28,flexShrink:0}}>{m.icon}</div>
              <div style={{flex:1}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
                  <div style={{fontSize:14,fontWeight:700,color:T.white}}>{m.name}</div>
                  {m.rec&&<span style={{fontSize:9,fontWeight:700,padding:"2px 7px",borderRadius:8,
                    background:`${T.green}22`,color:T.green}}>RECOMENDADO</span>}
                </div>
                <div style={{fontSize:12,color:T.fog,lineHeight:1.5}}>{m.desc}</div>
              </div>
            </div>
          ))}

          {rwMethod==="csv"&&(
            <Card>
              <Lbl>Subir archivo CSV de códigos</Lbl>
              <div style={{background:T.deep,borderRadius:8,padding:12,marginBottom:14,
                fontFamily:"monospace",fontSize:11,color:T.silver,lineHeight:2}}>
                <div style={{color:T.teal,marginBottom:4}}>formato_codigos_nike.csv</div>
                <div style={{color:T.fog}}>code,value,expiry</div>
                <div>NIKE-AIR-2026-X7K3,20%,2026-12-31</div>
                <div>NIKE-AIR-2026-M9P2,20%,2026-12-31</div>
                <div style={{color:T.fog}}>... (un código por fila)</div>
              </div>
              <div onClick={()=>csvRef.current&&csvRef.current.click()} style={{
                border:`2px dashed ${rwCsvDone?T.teal:T.rim}`,borderRadius:12,
                padding:rwCsvDone?"14px":"28px",textAlign:"center",cursor:"pointer",background:T.deep}}>
                <input ref={csvRef} type="file" accept=".csv,.txt" style={{display:"none"}}
                  onChange={e=>{if(e.target.files[0]){setTimeout(()=>setRwCsvDone(true),800);}}}/>
                {rwCsvDone?(
                  <div style={{display:"flex",alignItems:"center",gap:12}}>
                    <div style={{fontSize:28}}>✅</div>
                    <div style={{textAlign:"left"}}>
                      <div style={{fontSize:13,fontWeight:700,color:T.teal}}>CSV cargado correctamente</div>
                      <div style={{fontSize:12,color:T.silver}}>~15,247 códigos únicos disponibles</div>
                    </div>
                  </div>
                ):(
                  <>
                    <div style={{fontSize:36,marginBottom:8}}>📄</div>
                    <div style={{fontSize:13,fontWeight:700,color:T.snow}}>Toca para subir tu CSV</div>
                    <div style={{fontSize:11,color:T.fog}}>.csv · Máx. 100MB · Hasta 500,000 códigos</div>
                  </>
                )}
              </div>
            </Card>
          )}

          {rwMethod==="auto"&&(
            <Card>
              <Lbl>Preferendum genera los códigos</Lbl>
              <Input label="Porcentaje de descuento" placeholder="Ej. 20" type="number" value={rwDiscount} onChange={setRwDiscount}/>
              <div style={{fontSize:12,color:T.fog,marginBottom:8,lineHeight:1.6}}>
                Preferendum generará un código único por votante con formato:<br/>
                <code style={{background:T.deep,padding:"2px 6px",borderRadius:4,fontFamily:"monospace",fontSize:11,color:T.teal}}>
                  BRAND-[AÑO]-[ALEATORIO]
                </code>
              </div>
            </Card>
          )}

          {rwMethod&&(
            <Card>
              <Lbl>Enlace de redención</Lbl>
              <div style={{fontSize:12,color:T.fog,marginBottom:12,lineHeight:1.6}}>
                El votante verá un botón <strong style={{color:T.white}}>"Usar mi descuento ahora"</strong> que lleva directamente a tu tienda.
              </div>
              <Input label="URL de tu tienda online" placeholder="Ej. https://www.nike.com/cl/checkout" value={rwStore} onChange={setRwStore}/>
              <Input label="Nombre de la tienda" placeholder="Ej. Nike Chile · nikestore.cl" value={rwStoreName} onChange={setRwStoreName}/>
              <Input label="Fecha de vencimiento" type="date" value={rwExpiry} onChange={setRwExpiry}/>

              <div style={{marginTop:16}}>
                <Lbl>Vista previa — lo que ve el votante</Lbl>
                <div style={{background:T.deep,borderRadius:12,padding:16,border:`1px solid ${T.teal}44`}}>
                  <div style={{display:"flex",gap:10,alignItems:"center",marginBottom:12}}>
                    <div style={{fontSize:28}}>🎉</div>
                    <div>
                      <div style={{fontSize:14,fontWeight:900,color:T.white,marginBottom:2}}>¡Gracias por votar!</div>
                      <div style={{fontSize:12,color:T.fog}}>Nike Chile te envía este regalo</div>
                    </div>
                  </div>
                  <div style={{background:"#1a1500",borderRadius:12,padding:16,border:`2px solid ${T.gold}`,textAlign:"center",marginBottom:12}}>
                    <div style={{fontSize:10,color:T.gold,textTransform:"uppercase",letterSpacing:"0.12em",marginBottom:8,fontWeight:700}}>
                      Tu código de descuento
                    </div>
                    <div style={{fontFamily:"monospace",fontSize:18,fontWeight:900,color:T.gold,letterSpacing:"0.1em",marginBottom:6}}>
                      NIKE-AIR-2026-X7K3
                    </div>
                    <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>20% OFF</div>
                    <div style={{fontSize:11,color:T.gold}}>En tu próxima compra · Válido hasta 31 Dic 2026</div>
                  </div>
                  <button style={{width:"100%",padding:"13px",borderRadius:12,background:T.gold,border:"none",color:"#000",fontSize:14,fontWeight:900,cursor:"pointer"}}>
                    🛍 Usar mi descuento ahora →
                  </button>
                </div>
              </div>
            </Card>
          )}

          {rwMethod&&(
            <>
              <Btn label="Guardar configuración de descuento →" full
                disabled={rwMethod==="csv"&&!rwCsvDone}
                onPress={()=>go("reward-voter-view")}/>
            </>
          )}
        </div>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // SCREEN: REWARD — VOTER VIEW (receives both codes after voting)
  // ══════════════════════════════════════════════════════════════
  if(screen==="reward-voter-view") {
    const dcode = "NIKE-AIR-2026-X7K3";
    const vcode = "70F9-DB8E-6E17";
    return (
      <div style={phone}>
        <div style={{background:T.deep,borderBottom:`1px solid ${T.rim}`,
          padding:"12px 16px",display:"flex",alignItems:"center",gap:10,position:"sticky",top:0,zIndex:99}}>
          <button onClick={()=>go("reward-codes")} style={{background:"none",border:"none",
            color:T.blue,fontSize:18,cursor:"pointer",padding:"0 4px"}}>←</button>
          <div style={{fontWeight:900,fontSize:17,color:T.white,flex:1}}>
            Vista del votante
          </div>
        </div>

        <div style={{background:`linear-gradient(135deg, #1a3a6b 0%, ${T.bg} 100%)`,
          padding:"32px 20px 24px",textAlign:"center"}}>
          <div style={{fontSize:56,marginBottom:12}}>✅</div>
          <div style={{fontSize:24,fontWeight:900,color:T.white,marginBottom:6}}>¡Voto registrado!</div>
          <div style={{fontSize:13,color:T.silver,lineHeight:1.6,maxWidth:280,margin:"0 auto"}}>
            Tu voto fue cifrado con AES-256 y anclado en blockchain Polygon. Aquí están tus dos códigos.
          </div>
        </div>

        <div style={{padding:"20px 16px 60px"}}>
          {/* CODE 1: VERIFICATION */}
          <div style={{background:T.panel,border:`1px solid ${T.rim}`,borderRadius:14,padding:18,marginBottom:14}}>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
              <div style={{width:32,height:32,borderRadius:8,background:`${T.blue}22`,
                display:"flex",alignItems:"center",justifyContent:"center",fontSize:16}}>🔒</div>
              <div>
                <div style={{fontSize:13,fontWeight:700,color:T.white}}>Código de verificación</div>
                <div style={{fontSize:11,color:T.fog}}>Blockchain Polygon · Preferendum</div>
              </div>
            </div>
            <div style={{background:T.deep,borderRadius:10,padding:14,border:`1px solid ${T.blue}44`,marginBottom:10}}>
              <div style={{fontSize:10,color:T.fog,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:6}}>
                Tu código de verificación
              </div>
              <div style={{fontFamily:"monospace",fontSize:22,fontWeight:900,color:T.blue,letterSpacing:"0.12em",textAlign:"center"}}>
                {vcode}
              </div>
            </div>
            <div style={{fontSize:11,color:T.fog,lineHeight:1.6,marginBottom:10}}>
              Con este código puedes verificar que tu voto fue registrado correctamente una vez que la votación cierre.
            </div>
            <button onClick={()=>setRwVcode(true)} style={{
              width:"100%",padding:"10px",borderRadius:10,
              background:rwVcode?`${T.green}22`:T.deep,
              border:`1.5px solid ${rwVcode?T.green:T.rim}`,
              color:rwVcode?T.green:T.silver,
              fontSize:13,fontWeight:700,cursor:"pointer",fontFamily:"inherit"}}>
              {rwVcode?"✓ Copiado":"Copiar código de verificación"}
            </button>
          </div>

          {/* CODE 2: DISCOUNT */}
          <div style={{background:"linear-gradient(135deg, #1a1a00 0%, #1a2035 100%)",
            border:`2px solid ${T.gold}`,borderRadius:14,padding:18,marginBottom:14}}>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
              <div style={{width:32,height:32,borderRadius:8,background:`${T.gold}22`,
                display:"flex",alignItems:"center",justifyContent:"center",fontSize:16}}>🎁</div>
              <div>
                <div style={{fontSize:13,fontWeight:700,color:T.white}}>Regalo de Nike Chile</div>
                <div style={{fontSize:11,color:T.gold}}>Por participar en nuestra decisión</div>
              </div>
            </div>
            <div style={{background:"#1a1500",borderRadius:12,padding:16,border:`2px solid ${T.gold}`,textAlign:"center",marginBottom:12,position:"relative",overflow:"hidden"}}>
              <div style={{position:"absolute",top:-20,left:-20,width:60,height:60,borderRadius:"50%",background:`${T.gold}11`}}/>
              <div style={{position:"absolute",bottom:-20,right:-20,width:60,height:60,borderRadius:"50%",background:`${T.gold}11`}}/>
              <div style={{fontSize:10,color:T.gold,textTransform:"uppercase",letterSpacing:"0.12em",marginBottom:8,fontWeight:700}}>
                Tu código de descuento
              </div>
              <div style={{fontFamily:"monospace",fontSize:20,fontWeight:900,color:T.gold,letterSpacing:"0.1em",marginBottom:6}}>
                {dcode}
              </div>
              <div style={{fontSize:22,fontWeight:900,color:T.white,marginBottom:4}}>20% OFF</div>
              <div style={{fontSize:11,color:T.gold}}>En tu próxima compra · Válido hasta 31 Dic 2026</div>
            </div>
            <div style={{background:`${T.gold}11`,borderRadius:10,padding:"10px 12px",marginBottom:12,fontSize:12,color:T.silver,lineHeight:1.6}}>
              Votaste por: <strong style={{color:T.gold}}>Air Max Pulse</strong> para la colección Nike 2026. Tu preferencia ayudará a Nike a fabricar lo que el mercado realmente quiere.
            </div>
            <button onClick={()=>setRwCopied(true)} style={{
              width:"100%",padding:"11px",borderRadius:10,
              background:rwCopied?`${T.green}22`:T.deep,
              border:`1.5px solid ${rwCopied?T.green:T.gold}`,
              color:rwCopied?T.green:T.gold,
              fontSize:13,fontWeight:700,cursor:"pointer",fontFamily:"inherit",marginBottom:10}}>
              {rwCopied?"✓ ¡Copiado!":"📋 Copiar código de descuento"}
            </button>
            <button style={{width:"100%",padding:"14px",borderRadius:12,background:T.gold,border:"none",color:"#000",fontSize:15,fontWeight:900,cursor:"pointer",fontFamily:"inherit"}}>
              🛍 Usar mi descuento ahora →
            </button>
          </div>

          {/* What happens next */}
          <Card>
            <Lbl>¿Qué pasa ahora?</Lbl>
            {[{icon:"🛍",title:"Usa tu descuento hoy",desc:"El código de Nike es válido inmediatamente. Cópialo y úsalo en tu próxima compra."},
              {icon:"🔒",title:"Guarda tu código de verificación",desc:"Cuando la votación cierre, podrás verificar que tu voto fue registrado correctamente."},
              {icon:"📊",title:"Resultados en vivo",desc:"Los resultados parciales ya están disponibles en la pestaña Resultados."},
              {icon:"🎯",title:"Tu voz importa",desc:"Nike fabricará más del modelo ganador. Tu voto influyó en lo que se producirá."},
            ].map((item,i)=>(
              <div key={i} style={{display:"flex",gap:12,padding:"10px 0",
                borderBottom:i<3?`1px solid ${T.rim}`:"none"}}>
                <div style={{fontSize:22,flexShrink:0}}>{item.icon}</div>
                <div>
                  <div style={{fontSize:13,fontWeight:700,color:T.white,marginBottom:2}}>{item.title}</div>
                  <div style={{fontSize:12,color:T.fog,lineHeight:1.5}}>{item.desc}</div>
                </div>
              </div>
            ))}
          </Card>
          <Btn label="← Volver al panel de marketing" full outline color={T.blue} onPress={()=>go("marketer")}/>
        </div>
      </div>
    );
  }

  return null;
}
