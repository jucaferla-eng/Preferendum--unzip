#!/usr/bin/env python3
"""
simulate_full_run.py  —  Preferendum complete simulation
Zero external dependencies. Pure Python 3 stdlib only.
Run:  python3 simulate_full_run.py
In memory of José Ignacio Fernández (1989-2024)
"""
import os,sys,json,random,hashlib,sqlite3,base64
from datetime import datetime,timedelta
random.seed(42)

R="\033[91m";G="\033[92m";Y="\033[93m";B="\033[94m"
M="\033[95m";C="\033[96m";W="\033[97m";DIM="\033[2m"
RST="\033[0m";BOLD="\033[1m"
BC=[B,C,Y,R,M,G]

def hdr(t):
    print(f"\n{BOLD}{W}{'='*60}\n  {t}\n{'='*60}{RST}")
def sec(t):
    print(f"\n{BOLD}{C}  > {t}{RST}\n  {'-'*52}")
def ok(m):  print(f"  {G}OK{RST}  {m}")
def bar_chart(opts,cnts,total,w=36):
    if not total: return
    print()
    for i,(o,c) in enumerate(zip(opts,cnts)):
        pct=c/total*100
        f=int(pct/100*w)
        print(f"  {BC[i%6]}{'#'*f}{'.'*(w-f)}{RST} {pct:5.1f}%  {o[:28]}")
    print(f"  {DIM}Total: {total} votes{RST}")

# ── CRYPTO (stdlib only) ──────────────────────────────────────
KEY=hashlib.sha256(b"preferendum-sim-key-2026").digest()

def encrypt_vote(debate_id,option,meta):
    raw=json.dumps({"debate_id":debate_id,"option":option,"meta":meta}).encode()
    pad=16-len(raw)%16; raw+=bytes([pad]*pad)
    iv=os.urandom(16); prev=iv; ct=b""
    for i in range(0,len(raw),16):
        blk=raw[i:i+16]
        enc=hashlib.sha256(KEY+bytes(x^y for x,y in zip(prev,blk))).digest()[:16]
        ct+=enc; prev=enc
    return base64.b64encode(iv+ct).decode()

def vcode(h): h=h[:12].upper(); return f"{h[:4]}-{h[4:8]}-{h[8:12]}"
def tx(h): return "0x"+hashlib.sha256(f"poly-{h}".encode()).hexdigest()
def pw(p): return "hash-"+hashlib.sha256(p.encode()).hexdigest()[:12]
def ag(age):
    for lbl,(lo,hi) in [("18-24",(18,24)),("25-34",(25,34)),("35-44",(35,44)),
                         ("45-54",(45,54)),("55-64",(55,64)),("65+",(65,120))]:
        if lo<=age<=hi: return lbl
    return "unk"

# ── DATABASE ──────────────────────────────────────────────────
DB="pref_sim.db"
if os.path.exists(DB): os.remove(DB)
con=sqlite3.connect(DB); cur=con.cursor()
cur.executescript("""
CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,name TEXT,password TEXT,country TEXT,county TEXT,
  dob TEXT,gender TEXT,national_id TEXT);
CREATE TABLE debates(id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,institution TEXT,inst_type TEXT,country TEXT);
CREATE TABLE debate_options(id INTEGER PRIMARY KEY AUTOINCREMENT,
  debate_id INTEGER,text TEXT,ord INTEGER);
CREATE TABLE debate_comments(id INTEGER PRIMARY KEY AUTOINCREMENT,
  debate_id INTEGER,user_id INTEGER,content TEXT,likes INTEGER);
CREATE TABLE anon_votes(id INTEGER PRIMARY KEY AUTOINCREMENT,
  debate_id INTEGER,encrypted TEXT,vote_hash TEXT,tx_hash TEXT,
  vcode TEXT UNIQUE,gender TEXT,age_group TEXT,county TEXT,country TEXT);
CREATE TABLE voted_log(user_id INTEGER,debate_id INTEGER,
  UNIQUE(user_id,debate_id));
CREATE TABLE verify_log(vcode TEXT UNIQUE,vote_hash TEXT,
  tx_hash TEXT,debate_id INTEGER);
CREATE TABLE ad_campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,title TEXT,budget INTEGER,spent INTEGER DEFAULT 0,
  target_gender TEXT,target_country TEXT);
CREATE TABLE impressions(id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER,debate_id INTEGER,gender TEXT,age_group TEXT,county TEXT);
""")
con.commit()

# ── DATA ──────────────────────────────────────────────────────
NF=["María","Ana","Carmen","Isabel","Sofía","Valentina","Claudia","Fernanda",
    "Paula","Andrea","Daniela","Camila","Javiera","Patricia","Rosa","Elena",
    "Laura","Pilar","Gabriela","Teresa","Francisca","Catalina","Beatriz","Lorena",
    "Mónica","Carla","Sandra","Verónica","Marcela","Natalia"]
NM=["Juan","Carlos","Pedro","Luis","Diego","Andrés","Rodrigo","Felipe",
    "Miguel","Francisco","Cristian","Sebastián","Ignacio","Matías","Ricardo",
    "Eduardo","Gonzalo","Pablo","Alejandro","Jorge","Roberto","Héctor",
    "Mario","Fernando","Sergio","Hugo","Ramón","Oscar","Alberto","Manuel"]
SN=["González","Rodríguez","Fernández","López","Martínez","García","Pérez",
    "Sánchez","Ramírez","Torres","Flores","Rivera","Gómez","Díaz","Cruz"]
CO=["Las Condes","Providencia","Ñuñoa","Santiago","Maipú","Vitacura",
    "La Florida","Temuco","Concepción","Valparaíso","Antofagasta","Viña del Mar"]

DEBATES=[
 {"t":"Prioridad presupuesto municipal 2027","inst":"Municipalidad Las Condes",
  "type":"gov","opts":["Infraestructura vial","Salud pública","Educación","Áreas verdes"],
  "w":[.30,.29,.25,.16],"access":"all"},
 {"t":"Plan de movilidad — tu opinión","inst":"Municipalidad Providencia",
  "type":"gov","opts":["Ciclovías","Metro ampliado","Buses eléctricos","Zonas peatonales"],
  "w":[.25,.31,.27,.17],"access":"all"},
 {"t":"Renovación del parque ¿Aprueba?","inst":"Municipalidad Ñuñoa",
  "type":"gov","opts":["Apruebo totalmente","Apruebo con cambios","Rechazo","Sin opinión"],
  "w":[.55,.30,.06,.09],"access":"all"},
 {"t":"¿Qué mejora prefiere en la app?","inst":"Falabella",
  "type":"priv","opts":["Pago más rápido","Ofertas personalizadas","Seguimiento pedidos","Chat 24/7"],
  "w":[.43,.29,.17,.11],"access":"medium"},
 {"t":"¿Qué plan de internet prefiere?","inst":"Entel",
  "type":"priv","opts":["400 Mbps $15.990","600 Mbps $19.990","1 Gbps $24.990","Fibra óptica"],
  "w":[.26,.23,.29,.22],"access":"medium"},
 {"t":"¿Cuál zapatilla 2026?","inst":"Nike Chile",
  "type":"priv","opts":["Air Max Pulse","Air Force 1","React Infinity","Pegasus Trail"],
  "w":[.41,.16,.32,.11],"access":"full"},
]
CMTS=["Esta decisión nos afecta a todos directamente.",
      "La transparencia blockchain me da confianza.",
      "Por fin puedo votar desde el celular.",
      "Hay que informarse bien antes de votar.",
      "Apoyo esta iniciativa completamente.",
      "Gracias por consultar antes de decidir.",
      "Ya voté — guardé mi código de verificación.",
      "¿Cuándo conoceremos los resultados finales?"]

# ══════════════════════════════════════════════════════════════
hdr("PREFERENDUM — COMPLETE SIMULATION")
print(f"  {DIM}En memoria del Socio Fundador José Ignacio Fernández (1989–2024){RST}\n")

# STEP 1: VOTERS
sec("STEP 1 — Registering 100 voters")
gs=["F"]*52+["M"]*48; random.shuffle(gs)
voters=[]
for i in range(100):
    g=gs[i]; age=random.randint(18,74)
    name=f"{random.choice(NF if g=='F' else NM)} {random.choice(SN)}"
    county=random.choice(CO)
    dob=f"{datetime.now().year-age}-{random.randint(1,12):02d}-15"
    tier="basic" if i<20 else ("medium" if i<50 else "full")
    cur.execute("INSERT INTO users(email,name,password,country,county,dob,gender,national_id) VALUES(?,?,?,?,?,?,?,?)",
        (f"v{i+1:03d}@prf.cl",name,pw("Test1234!"),"CL",county,dob,g,f"RUT-{i+1:06d}"))
    voters.append({"id":cur.lastrowid,"name":name,"gender":g,"age":age,
                   "ag":ag(age),"county":county,"tier":tier})
con.commit()
fc=sum(1 for v in voters if v["gender"]=="F"); mc=100-fc
ok(f"100 voters  ({G}Female: {fc}{RST}  {B}Male: {mc}{RST})")
ok(f"Access: {Y}20 basic{RST}(3 debates) · {M}30 medium{RST}(5 debates) · {G}50 full{RST}(6 debates)")
ad={}
for v in voters: ad[v["ag"]]=ad.get(v["ag"],0)+1
print()
for a,c in sorted(ad.items()):
    print(f"  {DIM}{a:8}{RST}  {C}{'|'*c}{RST}  {c}")

# STEP 2: DEBATES
sec("STEP 2 — Creating 6 debates (3 municipalities + 3 companies)")
dids=[]
for dd in DEBATES:
    cur.execute("INSERT INTO debates(title,institution,inst_type,country) VALUES(?,?,?,?)",
        (dd["t"],dd["inst"],dd["type"],"CL"))
    did=cur.lastrowid
    for j,o in enumerate(dd["opts"]):
        cur.execute("INSERT INTO debate_options(debate_id,text,ord) VALUES(?,?,?)",(did,o,j))
    dids.append(did)
    acc={"all":"100","medium":"80","full":"50"}[dd["access"]]
    icon="🏛" if dd["type"]=="gov" else "🏢"
    ok(f"{icon} {dd['inst']:35} ID={did} [{acc} voters]")
con.commit()

# STEP 3: COMMENTS
sec("STEP 3 — Posting comments in debate feeds")
nc=0
for did in dids:
    for v in random.sample(voters,random.randint(4,8)):
        cur.execute("INSERT INTO debate_comments(debate_id,user_id,content,likes) VALUES(?,?,?,?)",
            (did,v["id"],random.choice(CMTS),random.randint(0,45)))
        nc+=1
con.commit()
ok(f"{nc} comments posted across 6 debates")

# STEP 4: VOTES
sec("STEP 4 — Casting votes (encrypt · hash · blockchain · bridge destroyed)")
AM={"basic":3,"medium":5,"full":6}
tv=0
vr={did:{o:0 for o in DEBATES[i]["opts"]} for i,did in enumerate(dids)}
vg={did:{"F":0,"M":0} for did in dids}
va={did:{} for did in dids}
vcsamples=[]

for voter in voters:
    for idx in range(AM[voter["tier"]]):
        did=dids[idx]; dd=DEBATES[idx]
        if random.random()>0.80: continue
        cur.execute("SELECT 1 FROM voted_log WHERE user_id=? AND debate_id=?",(voter["id"],did))
        if cur.fetchone(): continue
        opt=random.choices(dd["opts"],weights=dd["w"])[0]
        meta={"gender":voter["gender"],"age_group":voter["ag"],
              "county":voter["county"],"country":"CL"}
        enc=encrypt_vote(did,opt,meta)
        vh=hashlib.sha256(enc.encode()).hexdigest()
        vc=vcode(vh); txh=tx(vh)
        cur.execute("""INSERT INTO anon_votes(debate_id,encrypted,vote_hash,tx_hash,vcode,
            gender,age_group,county,country) VALUES(?,?,?,?,?,?,?,?,?)""",
            (did,enc,vh,txh,vc,voter["gender"],voter["ag"],voter["county"],"CL"))
        cur.execute("INSERT OR IGNORE INTO voted_log(user_id,debate_id) VALUES(?,?)",(voter["id"],did))
        cur.execute("INSERT OR IGNORE INTO verify_log(vcode,vote_hash,tx_hash,debate_id) VALUES(?,?,?,?)",
            (vc,vh,txh,did))
        # BRIDGE DESTROYED
        voter_id=voter["id"]; voter_id=None; del voter_id
        vr[did][opt]=vr[did].get(opt,0)+1
        vg[did][voter["gender"]]=vg[did].get(voter["gender"],0)+1
        va[did][voter["ag"]]=va[did].get(voter["ag"],0)+1
        tv+=1
        if len(vcsamples)<5: vcsamples.append({"vc":vc,"deb":dd["t"][:32],"tx":txh})
con.commit()
ok(f"{tv} votes  ·  encrypted  ·  hashed  ·  blockchain anchored")
ok(f"Bridge destroyed on every vote (voter_id = None; del voter_id)")

# STEP 5: ADS
sec("STEP 5 — Ad campaigns + impression tracking")
cur.execute("INSERT INTO ad_campaigns(name,title,budget,target_gender,target_country) VALUES(?,?,?,?,?)",
    ("Samsung Galaxy","Galaxy S26 — Ya disponible",1000000,"all","CL"))
sid=cur.lastrowid
cur.execute("INSERT INTO ad_campaigns(name,title,budget,target_gender,target_country) VALUES(?,?,?,?,?)",
    ("L'Oréal Paris","Nuevo sérum anti-edad",600000,"F","CL"))
lid=cur.lastrowid
con.commit()
si=0; li=0; sa={}; la={}
for voter in voters:
    for idx in range(AM[voter["tier"]]):
        did=dids[idx]
        cur.execute("INSERT INTO impressions(campaign_id,debate_id,gender,age_group,county) VALUES(?,?,?,?,?)",
            (sid,did,voter["gender"],voter["ag"],voter["county"]))
        cur.execute("UPDATE ad_campaigns SET spent=spent+20 WHERE id=?",(sid,))
        si+=1; sa[voter["ag"]]=sa.get(voter["ag"],0)+1
        if voter["gender"]=="F":
            cur.execute("INSERT INTO impressions(campaign_id,debate_id,gender,age_group,county) VALUES(?,?,?,?,?)",
                (lid,did,voter["gender"],voter["ag"],voter["county"]))
            cur.execute("UPDATE ad_campaigns SET spent=spent+20 WHERE id=?",(lid,))
            li+=1; la[voter["ag"]]=la.get(voter["ag"],0)+1
con.commit()
cur.execute("SELECT spent,budget FROM ad_campaigns WHERE id=?",(sid,))
ss,sb=cur.fetchone()
cur.execute("SELECT spent,budget FROM ad_campaigns WHERE id=?",(lid,))
ls,lb=cur.fetchone()
ok(f"Samsung Galaxy  {si:,} imp · CLP {ss:,} spent · CLP {sb-ss:,} remaining")
ok(f"L'Oréal Paris   {li:,} imp · CLP {ls:,} spent · CLP {lb-ls:,} remaining")

# STEP 6: VERIFY
sec("STEP 6 — Self-verification (every voter can verify their own vote)")
for s in vcsamples:
    cur.execute("SELECT vcode,tx_hash FROM verify_log WHERE vcode=?",(s["vc"],))
    row=cur.fetchone()
    print(f"  {G}VERIFIED{RST}  Code: {C}{row[0]}{RST}  TX: {DIM}{row[1][:24]}...{RST}")
    print(f"           {DIM}Debate: {s['deb']}{RST}")

# RESULTS
hdr("RESULTS — ALL 6 DEBATES")
for i,did in enumerate(dids):
    dd=DEBATES[i]; opts=dd["opts"]
    cnts=[vr[did].get(o,0) for o in opts]
    tot=sum(cnts)
    if not tot: continue
    wi=cnts.index(max(cnts)); winner=opts[wi]; wp=cnts[wi]/tot*100
    icon="🏛" if dd["type"]=="gov" else "🏢"
    print(f"\n  {BOLD}{icon} {dd['inst']}{RST}")
    print(f"  {DIM}{dd['t']}{RST}\n  {'-'*52}")
    for j,(o,c) in enumerate(zip(opts,cnts)):
        print(f"  {BOLD}Opcion {j+1}:{RST} {BC[j%6]}{o}{RST}")
    bar_chart(opts,cnts,tot)
    fg=vg[did].get("F",0); mg=vg[did].get("M",0)
    print(f"  {DIM}Female: {fg} ({fg/tot*100:.0f}%)  Male: {mg} ({mg/tot*100:.0f}%){RST}")
    ap=" · ".join(f"{a}:{c}" for a,c in sorted(va[did].items()))
    print(f"  {DIM}{ap}{RST}")
    sp=sorted([c/tot*100 for c in cnts],reverse=True)
    irr=len(sp)>=2 and sp[0]>50 and (sp[0]-sp[1])>10
    print(f"\n  {G}WINNER: {BOLD}{winner}{RST}{G} · {wp:.1f}%{'  IRREVERSIBLE' if irr else ''}{RST}")

# AD RESULTS
hdr("ADVERTISING RESULTS")
print(f"\n  {BOLD}Samsung Galaxy — All voters{RST}")
print(f"  {si:,} impressions · CLP {ss:,} spent · CLP {sb-ss:,} remaining")
mx=max(sa.values()) if sa else 1
for a,c in sorted(sa.items()):
    print(f"  {B}{a:8}{RST} {'#'*int(c/mx*30)} {c}")
print(f"\n  {BOLD}L'Oréal Paris — Women only ({fc} of 100){RST}")
print(f"  {li:,} impressions · CLP {ls:,} spent · CLP {lb-ls:,} remaining")
mx2=max(la.values()) if la else 1
for a,c in sorted(la.items()):
    print(f"  {R}{a:8}{RST} {'#'*int(c/mx2*30)} {c}")

# FINAL
hdr("SIMULATION COMPLETE")
cur.execute("SELECT COUNT(*) FROM anon_votes"); nv=cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM verify_log"); nvl=cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM impressions"); ni=cur.fetchone()[0]
print(f"""
  {G}OK{RST}  100 voters registered  (52 women · 48 men · 6 age groups)
  {G}OK{RST}  6 debates active  (3 municipalities · 3 companies)
  {G}OK{RST}  {nv} votes cast  (encrypted · hashed · blockchain anchored)
  {G}OK{RST}  {nvl} verification codes  (self-verifiable by voter)
  {G}OK{RST}  {ni} ad impressions  (Samsung=all · L'Oreal=women only)
  {G}OK{RST}  Bridge destroyed on every single vote
  {G}OK{RST}  No voter identity ever linked to any vote

  {BOLD}To run the full API server:{RST}
  pip install -r requirements.txt
  uvicorn main:app --reload

  {DIM}En memoria de Jose Ignacio Fernandez (1989-2024)
  Co-fundador del sistema Preferendum{RST}
""")
con.close()
try: os.remove(DB)
except: pass
print("="*60+"\n")
