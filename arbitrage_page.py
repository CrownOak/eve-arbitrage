#!/usr/bin/env python3
"""
BONK Hub Arbitrage : page renderer (sortable, searchable, data driven).
Per item: the profitable route (buy hub > sell hub), jumps between them, net profit per unit and
per m3 after fees, and net ISK per jump for a full cargo hold (the headline: travel is the job).
A Model toggle switches LIST (relist, patient) vs FLIP (instant sell into buy orders); a Route
toggle switches Highsec vs Shortest jumps. Tax, broker, freight, cargo and min volume are editable;
the page nets the RAW baked prices client side so the operator tunes them. Baked hourly. No live calls.
"""
import html, json, os, tempfile

REFRESH_SECONDS = 3600


def _esc(v):
    return "" if v is None or v == "" else html.escape(str(v))


def render_page(data):
    gen = _esc(data.get("generated_at", ""))
    n = _esc(data.get("item_count", ""))
    hubs = ", ".join(data.get("hubs") or [])
    d = data.get("defaults") or {}
    rows = data.get("rows") or []
    blob = json.dumps({"rows": rows, "defaults": d, "jumps": data.get("jumps") or {},
                       "danger": data.get("danger") or {}})
    if not rows:
        inner = '<div class="empty">No data yet. The hourly run will populate this page.</div>'
    else:
        inner = """
    <div class="rctl">
      <label class="rlab">Search <input id="q" type="text" placeholder="item name..." autocomplete="off"></label>
      <label class="rlab" data-tip="Sales tax paid on every market sale. Set it to your Accounting skill level.">Sales tax %
        <input id="tax" type="number" value="3.37" min="0" step="0.01"></label>
      <label class="rlab" data-tip="Broker fee paid to place a sell order (the LIST model only). Set it to your Broker Relations skill and standings.">Broker %
        <input id="broker" type="number" value="3.0" min="0" step="0.1"></label>
      <label class="rlab" data-tip="Your hauling cost in ISK per cubic metre. Folds into ISK/m3 and ISK/jump so you see what survives the trip.">Freight ISK/m&sup3;
        <input id="freight" type="number" value="0" min="0" step="1"></label>
      <label class="rlab" data-tip="How much cargo you fill per run, in cubic metres. A jump freighter is about 60000. ISK/jump never assumes more than this, or more than the destination can absorb.">Cargo m&sup3;
        <input id="cargo" type="number" value="60000" min="1" step="1000"></label>
      <label class="rlab" data-tip="Days of the destination's traded volume you move per trip. ISK/jump caps the haul at this many days of what the sell hub actually trades, so a thin market cannot pretend to fill a freighter.">Days of vol
        <input id="days" type="number" value="1" min="0.1" step="0.5"></label>
      <label class="rlab" data-tip="Hide items the destination trades fewer than this many units per day. A spread you cannot actually sell into is not an opportunity.">Min day vol
        <input id="minvol" type="number" value="100" min="0" step="50"></label>
    </div>
    <div class="rctl">
      <div class="toggle">Model
        <button id="mList" class="on">List</button>
        <button id="mFlip">Flip</button>
      </div>
      <div class="toggle">Route
        <button id="rSec" class="on">Highsec</button>
        <button id="rShort">Shortest</button>
      </div>
      <div class="toggle">Show
        <button id="tProfit" class="on">Profitable</button>
        <button id="tAll">All</button>
      </div>
    </div>
    <table><thead><tr>
      <th data-sort="n"      data-tip="Item name. A thin tag means one hub's cheapest sell order looks like a fat finger, so treat its margin with suspicion.">ITEM</th>
      <th data-sort="route"  data-tip="The profitable direction: buy at the first hub, sell at the second. Switches with the Model toggle (relist hub for LIST, the hub whose buy orders pay most for FLIP).">ROUTE</th>
      <th data-sort="jumps"  data-tip="Jumps between the two hubs on the selected route type. Highsec is the safe freighter route; Shortest is fewest jumps and may cross lowsec.">JUMPS</th>
      <th data-sort="danger" data-tip="Recent gank risk on the selected route: lowsec or null exposure plus PvP kills along the path, smoothed over recent hours. Switches with the Route toggle. Sort it to float the safe hauls to the top.">DANGER</th>
      <th data-sort="bc"     data-tip="Cost to buy one unit at the first hub, using the robust cheapest 5% sell price (not the single lowest order).">BUY COST</th>
      <th data-sort="net"    data-tip="Net ISK per unit on the selected model, after fees and before freight. LIST pays sales tax plus broker; FLIP pays sales tax only. Never guaranteed on the LIST model.">NET / UNIT</th>
      <th data-sort="margin" data-tip="Net profit as a percent of buy cost. How hard your ISK works.">MARGIN</th>
      <th data-sort="m3"     data-tip="Volume of one unit. Ships use packaged (transport) volume.">m&sup3;</th>
      <th data-sort="iskm3"  data-tip="Net ISK per cubic metre, after fees and your freight rate. Rank cargo by this when distance does not matter.">ISK / M&sup3;</th>
      <th data-sort="iskjump" data-tip="The headline: net ISK per jump for the cargo you can realistically move, after fees and freight. The haul is capped at your hold AND at the days of volume the destination actually trades, so thin markets cannot inflate it. Travel is the job, so this ranks routes by what each jump pays.">ISK / JUMP</th>
      <th data-sort="dvol"   data-tip="Average units actually TRADED per day at the sell hub (ESI market history). The real cap on how much one haul can move, not an order book snapshot.">DAY VOL</th>
    </tr></thead><tbody id="tb"></tbody></table>
"""
    sub = (f"buy low in one hub, sell high in another &middot; ranked by ISK per jump, because travel is the job "
           f"&middot; {n} items across {len(data.get('hubs') or [])} hubs ({_esc(hubs)}) "
           f"&middot; prices updated {gen} UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>BONK - Hub Arbitrage</title>
<link rel="stylesheet" href="/common.css?v=3">
<style>
  .rctl{{ display:flex; flex-wrap:wrap; align-items:center; gap:20px; margin:2px 0 16px; }}
  .rlab{{ display:flex; align-items:center; gap:8px; font-family:var(--mono); font-size:11px;
          letter-spacing:.05em; text-transform:uppercase; color:var(--muted); cursor:help; }}
  .rlab input{{ width:88px; padding:6px 9px; background:var(--black); border:1px solid var(--line);
          color:var(--silver); font-family:var(--mono); font-size:12px; }}
  th[data-sort]{{ cursor:pointer; }}
  th[data-sort]:hover{{ color:var(--laser); }}
  th .ar{{ color:var(--ore); margin-left:4px; font-size:10px; }}
  td.who{{ text-align:left; }}
  .dgr{{ display:inline-block; font-family:var(--mono); font-size:10px; font-weight:700; text-transform:uppercase;
         letter-spacing:.05em; padding:2px 8px; border:1px solid currentColor; cursor:help; }}
  .dgr.good{{ color:var(--ore); }} .dgr.warn{{ color:var(--amber); }} .dgr.bad{{ color:var(--red); }}
</style></head>
<body>
  <header>
    <h1>BIG ROCK ENERGY [BONK] &middot; HUB ARBITRAGE</h1>
    <div class="sub">{sub}</div>
  </header>
  <div class="wrap">{inner}</div>
  <footer>For a curated set of liquid, haulable items we pull buy and sell prices across the major
  trade hubs, work out the best cross hub spread, and rank by what each jump of travel earns.
  <b>ROUTE</b> is the profitable direction: buy at the first hub, sell at the second. <b>LIST</b>
  carries the item to the dearest other hub and relists it under the market (pays broker fee plus
  sales tax): bigger, but you wait and the price can move. <b>FLIP</b> sells instantly into the best
  buy orders at another hub (pays sales tax only): safe, smaller, available now. Switch with the
  Model toggle. The Show toggle defaults to Profitable (positive net and at least your Min sell vol
  at the buy hub); All reveals everything, thin and negative spreads included. <b>JUMPS</b> come
  from the in game route: Highsec is the safe freighter path,
  Shortest is fewest jumps and may cross lowsec. <b>ISK/JUMP</b> is the net profit for the cargo you
  can realistically move, divided by the jumps, so a fat margin twenty jumps away loses to a fair one
  next door. The haul is capped at your hold AND at the days of volume the destination actually trades
  (from ESI market history), so a spread in a market that only moves a few units a day cannot pretend
  to fill a freighter. <b>DAY VOL</b> is the average units traded per day at the sell hub, the real
  liquidity and the binding limit on most hauls. All figures are net of fees, never gross. Buy cost
  uses the robust cheapest 5% sell price so a single mispriced order cannot invent a margin; a
  <b>thin</b> tag flags an item whose lowest order diverges from that.
  <b>DANGER</b> scores recent gank risk on the selected route: any lowsec or null on the path reads
  deadly, otherwise it is PvP kills along the highsec path smoothed over recent hours. Hover it for the
  worst system on the route, and sort by it to keep the freighter alive.
  Prices are region level and refresh hourly. This is market data, not a promise of profit. Fly safe,
  the gank on the Tama gate is now a column.</footer>
<script>var DATA = {blob};</script>
<script>
(function(){{
  var D = DATA.rows, DF = DATA.defaults || {{}}, J = DATA.jumps || {{}}, DG = DATA.danger || {{}};
  var st = {{ tax:DF.tax!=null?DF.tax:3.37, broker:DF.broker!=null?DF.broker:3.0,
             freight:DF.freight||0, cargo:DF.cargo||60000, days:DF.days!=null?DF.days:1,
             minvol:DF.min_vol!=null?DF.min_vol:100,
             model:"list", flag:"secure", q:"", all:false, key:"iskjump", dir:-1 }};
  function isk(v){{ if(v==null) return "n/a"; var a=Math.abs(v);
    if(a>=1e9) return (v/1e9).toFixed(2)+"B"; if(a>=1e6) return (v/1e6).toFixed(2)+"M";
    if(a>=1e3) return (v/1e3).toFixed(1)+"k"; if(a>=1) return String(Math.round(v));
    return v.toFixed(2); }}
  function m3d(v){{ if(v==null||v<=0) return "n/a"; if(v>=1000) return (v/1000).toFixed(1)+"k";
    if(v>=1) return String(v); return v.toFixed(3).replace(/0+$/,"").replace(/\\.$/,""); }}
  function qty(v){{ v=v||0; if(v>=1e6) return (v/1e6).toFixed(2)+"M";
    if(v>=1e3) return (v/1e3).toFixed(1)+"k"; return String(v); }}
  function jumpsOf(from,to){{ if(!from||!to) return null; var f=J[st.flag]||{{}}; var r=f[from];
    if(!r) return null; var j=r[to]; return (j==null)?null:j; }}
  function esc(s){{ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/'/g,"&#39;"); }}
  function dangerOf(from,to){{ if(!from||!to) return null; var f=DG[st.flag]||{{}}; var r=f[from];
    if(!r) return null; return r[to]||null; }}
  function dtip(dg){{ if(!dg) return "Route danger unknown.";
    if(dg.band==="deadly") return "Deadly: "+(dg.worst||"crosses lowsec or null")+". Not a blind freighter run, take Highsec or scout it.";
    if(dg.band==="risky") return "Risky: hottest spot "+(dg.worst||"a gank chokepoint")+". Watch local and keep aligned.";
    return "Looks clear: "+(dg.worst||"no recent ganks on this path")+"."; }}
  // net the RAW baked prices with the current fee/freight/cargo inputs, for the selected model + route
  function calc(r){{
    var tax=st.tax/100, broker=st.broker/100, buy=r.bc, dest, net, dvol;
    if(st.model==="flip"){{ net=(r.fh!=null && r.fp!=null) ? (r.fp*(1-tax) - buy) : null; dest=(net!=null)?r.fh:null; dvol=(r.fdv!=null?r.fdv:0); }}  // tax only
    else {{ dest=r.lh; net=r.lp*(1-tax-broker) - buy; dvol=(r.ldv!=null?r.ldv:0); }}                       // tax + broker
    var m3=(r.m3 && r.m3>0) ? r.m3 : null;
    var iskm3=(net!=null && m3!=null) ? (net/m3 - st.freight) : null;        // after freight
    var jumps=jumpsOf(r.bh,dest);
    var units=(m3!=null) ? Math.min(st.cargo/m3, st.days*dvol) : null;       // hold OR days of what the dest trades
    var realM3=(units!=null) ? units*m3 : null;
    var iskjump=(iskm3!=null && jumps && realM3>0) ? (iskm3*realM3/jumps) : null;
    var margin=(net!=null && buy>0) ? (net/buy*100) : null;
    return {{ from:r.bh, dest:dest, jumps:jumps, buy:buy, net:net, m3:m3,
             iskm3:iskm3, iskjump:iskjump, margin:margin, dvol:dvol }};
  }}
  function sval(r,c){{ var v=calc(r);
    switch(c){{
      case "n": return r.n; case "route": return v.dest==null?null:(v.from+" "+v.dest);
      case "jumps": return v.jumps;
      case "danger": var dd=dangerOf(v.from,v.dest); return dd?dd.score:null;
      case "bc": return v.buy; case "net": return v.net;
      case "margin": return v.margin; case "m3": return v.m3; case "iskm3": return v.iskm3;
      case "iskjump": return v.iskjump; case "dvol": return v.dvol; default: return 0; }} }}
  function visible(r){{
    if(st.all) return true;
    var v=calc(r);
    return v.net!=null && v.net>0 && v.dvol>=st.minvol;                      // profitable + the dest actually trades it
  }}
  function cls(v){{ return v>0?"good":(v<0?"bad":""); }}
  function render(){{
    var q=st.q.toLowerCase();
    var src=D.filter(function(r){{
      if(q) return (r.n+" "+r.bh+" "+(r.fh||"")+" "+r.lh).toLowerCase().indexOf(q)>=0;  // search surfaces all matches, even illiquid
      return visible(r); }});
    src.sort(function(a,b){{ var x=sval(a,st.key), y=sval(b,st.key);
      if(x==null&&y==null) return 0; if(x==null) return 1; if(y==null) return -1;  // n/a always last
      if(typeof x==="string") return st.dir*x.localeCompare(y);
      return st.dir*(x-y); }});
    var h="";
    src.forEach(function(r){{ var v=calc(r);
      var tag=r.thin?" <span class='kbadge npc' data-tip='One hub has a lone cheap sell order well below the rest. The margin may be a fat finger, not a real spread.'>thin</span>":"";
      var route=v.from+" &rsaquo; "+(v.dest||"n/a");
      var dg=dangerOf(v.from,v.dest);
      var dgh=dg?("<span class='dgr "+(dg.band==="deadly"?"bad":(dg.band==="risky"?"warn":"good"))+"' data-tip='"+esc(dtip(dg))+"'>"+dg.band+"</span>"):"<span class='num'>n/a</span>";
      h+="<tr>"
        +"<td class='who'><span class='strong'>"+r.n+"</span>"+tag+"</td>"
        +"<td class='cat'>"+route+"</td>"
        +"<td class='num'>"+(v.jumps==null?"n/a":v.jumps)+"</td>"
        +"<td>"+dgh+"</td>"
        +"<td class='num'>"+isk(v.buy)+"</td>"
        +"<td class='num strong "+(v.net==null?"":cls(v.net))+"'>"+isk(v.net)+"</td>"
        +"<td class='num "+(v.margin==null?"":cls(v.margin))+"'>"+(v.margin==null?"n/a":Math.round(v.margin)+"%")+"</td>"
        +"<td class='num'>"+m3d(v.m3)+"</td>"
        +"<td class='num "+(v.iskm3==null?"":cls(v.iskm3))+"'>"+(v.iskm3==null?"n/a":isk(v.iskm3))+"</td>"
        +"<td class='num strong "+(v.iskjump==null?"":cls(v.iskjump))+"'>"+(v.iskjump==null?"n/a":isk(v.iskjump))+"</td>"
        +"<td class='num'>"+qty(v.dvol)+"</td></tr>"; }});
    if(!src.length) h="<tr><td colspan='11' class='empty' style='padding:24px'>No item matches \\""+st.q+"\\".</td></tr>";
    document.getElementById("tb").innerHTML=h;
    Array.prototype.forEach.call(document.querySelectorAll("th[data-sort]"), function(th){{
      var k=th.getAttribute("data-sort"); var old=th.querySelector(".ar"); if(old) old.remove();
      if(k===st.key){{ var s=document.createElement("span"); s.className="ar";
        s.textContent=st.dir<0?"\\u25BC":"\\u25B2"; th.appendChild(s); }} }});
  }}
  Array.prototype.forEach.call(document.querySelectorAll("th[data-sort]"), function(th){{
    th.onclick=function(){{ var k=th.getAttribute("data-sort");
      if(st.key===k) st.dir=-st.dir; else {{ st.key=k; st.dir=(k==="n"||k==="route")?1:-1; }}
      render(); }}; }});
  function bind(id, prop){{ document.getElementById(id).addEventListener("input", function(){{
    st[prop]=parseFloat(this.value)||0; render(); }}); }}
  bind("tax","tax"); bind("broker","broker"); bind("freight","freight"); bind("cargo","cargo"); bind("days","days"); bind("minvol","minvol");
  document.getElementById("q").addEventListener("input", function(){{ st.q=this.value.trim(); render(); }});
  function pair(aId,bId,fn){{ var A=document.getElementById(aId), B=document.getElementById(bId);
    A.onclick=function(){{ fn(true); A.classList.add("on"); B.classList.remove("on"); render(); }};
    B.onclick=function(){{ fn(false); B.classList.add("on"); A.classList.remove("on"); render(); }}; }}
  pair("mList","mFlip",function(first){{ st.model=first?"list":"flip"; }});
  pair("rSec","rShort",function(first){{ st.flag=first?"secure":"shortest"; }});
  pair("tProfit","tAll",function(first){{ st.all=!first; }});
  render();
}})();
</script>
<script src="/nav.js?v=2"></script>
</body></html>"""


def write_html(path, data, password=None, allow_plain=False):
    if not password and not allow_plain:
        raise ValueError("refusing to write an unlocked page: no password (set EVE_PAGE_PASSWORD "
                         "or pass allow_plain=True)")
    text = render_page(data)
    if password:
        import page_lock
        text = page_lock.lock_page(text, password, title="BONK - Hub Arbitrage")
    dpath = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=dpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        raise
    return path
