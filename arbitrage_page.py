#!/usr/bin/env python3
"""
BONK Hub Arbitrage : page renderer (sortable, searchable, data driven).
Per item: cheapest hub to buy, two ways to sell (instant flip into buy orders, patient relist),
net profit per unit and per m3 after fees, and the sell order depth as a liquidity proxy. Tax,
broker fee and freight are editable inputs; the page nets the RAW baked prices client side so the
operator tunes them to their own skills and hauling rate. Prices baked hourly. No live calls.
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
    blob = json.dumps({"rows": rows, "defaults": d})
    if not rows:
        inner = '<div class="empty">No data yet. The hourly run will populate this page.</div>'
    else:
        inner = """
    <div class="rctl">
      <label class="rlab">Search <input id="q" type="text" placeholder="item name..." autocomplete="off"></label>
      <label class="rlab" data-tip="Sales tax paid on every market sale. Set it to your Accounting skill level.">Sales tax %
        <input id="tax" type="number" value="3.37" min="0" step="0.01"></label>
      <label class="rlab" data-tip="Broker fee paid to place a sell order (the relist model only). Set it to your Broker Relations skill and standings.">Broker %
        <input id="broker" type="number" value="3.0" min="0" step="0.1"></label>
      <label class="rlab" data-tip="Your hauling cost in ISK per cubic metre. Folds into the ISK/m3 column so you see what survives the trip.">Freight ISK/m&sup3;
        <input id="freight" type="number" value="0" min="0" step="1"></label>
      <label class="rlab" data-tip="Hide items with thinner sell order depth than this at the deepest hub. A margin you cannot move is not an opportunity.">Min sell vol
        <input id="minvol" type="number" value="100" min="0" step="50"></label>
      <div class="toggle">Show
        <button id="tProfit" class="on">Profitable</button>
        <button id="tAll">All</button>
      </div>
    </div>
    <table><thead><tr>
      <th data-sort="n"      data-tip="Item name. A thin tag means one hub's cheapest sell order looks like a fat finger, so treat its margin with suspicion.">ITEM</th>
      <th data-sort="bh"     data-tip="The hub where this item is cheapest to acquire from sell orders.">BUY @</th>
      <th data-sort="bc"     data-tip="Cost to buy one unit at BUY @, using the robust cheapest 5% sell price (not the single lowest order).">BUY COST</th>
      <th data-sort="fh"     data-tip="The hub whose buy orders pay the most. Where you dump cargo instantly.">FLIP @</th>
      <th data-sort="flipu"  data-tip="Net ISK per unit if you instantly sell into buy orders at FLIP @, after sales tax. No broker fee on a sale into a buy order. Safe, lower.">FLIP / UNIT</th>
      <th data-sort="lh"     data-tip="The hub where you relist the item, undercutting the existing sell orders.">LIST @</th>
      <th data-sort="listu"  data-tip="Net ISK per unit if you relist at LIST @ and wait, after sales tax and broker fee, before freight. Patient, higher, never guaranteed.">LIST / UNIT</th>
      <th data-sort="margin" data-tip="LIST net profit as a percent of buy cost. How hard your ISK works on the patient model.">MARGIN</th>
      <th data-sort="m3"     data-tip="Volume of one unit. Ships use packaged (transport) volume.">m&sup3;</th>
      <th data-sort="iskm3"  data-tip="The headline metric: net ISK per cubic metre on the LIST model, after fees and your freight rate. Rank cargo by this.">ISK / M&sup3;</th>
      <th data-sort="vol"    data-tip="Units listed on sell orders at the deepest hub. A liquidity proxy, not daily traded volume.">SELL VOL</th>
    </tr></thead><tbody id="tb"></tbody></table>
"""
    sub = (f"buy low in one hub, sell high in another &middot; net of fees, ranked by ISK per m&sup3; "
           f"&middot; {n} items across {len(data.get('hubs') or [])} hubs ({_esc(hubs)}) "
           f"&middot; prices updated {gen} UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>BONK - Hub Arbitrage</title>
<link rel="stylesheet" href="https://crownoak.github.io/wdeve/common.css?v=3">
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
</style></head>
<body>
  <header>
    <h1>BIG ROCK ENERGY [BONK] &middot; HUB ARBITRAGE</h1>
    <div class="sub">{sub}</div>
  </header>
  <div class="wrap">{inner}</div>
  <footer>For a curated set of liquid, haulable items we pull buy and sell prices across the major
  trade hubs and show the best cross hub spread two ways. <b>FLIP</b> means you buy at BUY @ and
  instantly sell into the best buy orders at FLIP @ (pays sales tax only): safe, smaller, available
  now. <b>LIST</b> means you carry the item to LIST @ and relist it under the market (pays broker
  fee plus sales tax, before freight): bigger, but you wait and the price can move. Both are net of
  fees, never gross. Buy cost uses the robust cheapest 5% sell price so a single mispriced order
  cannot invent a fake margin; a <b>thin</b> tag flags an item whose lowest order diverges from
  that. SELL VOL is the units on sell orders at the deepest hub, a liquidity proxy. ISK/m&sup3; is
  the metric that matters for hauling. Prices are region level and refresh hourly. This is market
  data, not a promise of profit. Fly safe, the gank on the Tama gate is your problem.</footer>
<script>var DATA = {blob};</script>
<script>
(function(){{
  var D = DATA.rows, DF = DATA.defaults || {{}};
  var st = {{ tax:DF.tax!=null?DF.tax:3.37, broker:DF.broker!=null?DF.broker:3.0,
             freight:DF.freight||0, minvol:DF.min_vol!=null?DF.min_vol:100,
             q:"", all:false, key:"iskm3", dir:-1 }};
  function isk(v){{ if(v==null) return "n/a"; var a=Math.abs(v);
    if(a>=1e9) return (v/1e9).toFixed(2)+"B"; if(a>=1e6) return (v/1e6).toFixed(2)+"M";
    if(a>=1e3) return (v/1e3).toFixed(1)+"k"; if(a>=1) return String(Math.round(v));
    return v.toFixed(2); }}
  function m3d(v){{ if(v==null||v<=0) return "n/a"; if(v>=1000) return (v/1000).toFixed(1)+"k";
    if(v>=1) return String(v); return v.toFixed(3).replace(/0+$/,"").replace(/\\.$/,""); }}
  function qty(v){{ v=v||0; if(v>=1e6) return (v/1e6).toFixed(2)+"M";
    if(v>=1e3) return (v/1e3).toFixed(1)+"k"; return String(v); }}
  // net the RAW baked prices with the current fee + freight inputs
  function calc(r){{
    var tax=st.tax/100, broker=st.broker/100;
    var buy=r.bc;
    var flipNet=(r.fh!=null && r.fp!=null) ? (r.fp*(1-tax) - buy) : null;   // sale into buy order: tax only
    var listNet=r.lp*(1-tax-broker) - buy;                                  // relist: tax + broker
    var m3=(r.m3 && r.m3>0) ? r.m3 : null;
    var iskm3=(m3!=null) ? (listNet/m3 - st.freight) : null;                // headline: per m3, after freight
    var margin=(buy>0) ? (listNet/buy*100) : null;
    return {{ buy:buy, flipNet:flipNet, listNet:listNet, m3:m3, iskm3:iskm3, margin:margin, vol:r.vol }};
  }}
  function sval(r,c){{ var v=calc(r);
    switch(c){{
      case "n": return r.n; case "bh": return r.bh; case "fh": return r.fh||""; case "lh": return r.lh;
      case "bc": return v.buy; case "flipu": return v.flipNet;
      case "listu": return v.listNet; case "margin": return v.margin;
      case "m3": return v.m3; case "iskm3": return v.iskm3; case "vol": return v.vol;
      default: return 0; }} }}
  function visible(r){{
    if(st.all) return true;
    var v=calc(r);
    return v.listNet>0 && v.vol>=st.minvol;                                 // profitable + liquid by default
  }}
  function cls(v){{ return v>0?"good":(v<0?"bad":""); }}
  function render(){{
    var q=st.q.toLowerCase();
    var src=D.filter(function(r){{
      if(q) return (r.n+" "+r.bh+" "+(r.fh||"")+" "+r.lh).toLowerCase().indexOf(q)>=0;  // search surfaces all matches, even illiquid
      return visible(r); }});
    src.sort(function(a,b){{ var x=sval(a,st.key), y=sval(b,st.key);
      if(typeof x==="string") return st.dir*x.localeCompare(y);
      if(x==null&&y==null) return 0; if(x==null) return 1; if(y==null) return -1;  // n/a always last
      return st.dir*(x-y); }});
    var h="";
    src.forEach(function(r){{ var v=calc(r);
      var tag=r.thin?" <span class='kbadge npc' data-tip='One hub has a lone cheap sell order well below the rest. The margin may be a fat finger, not a real spread.'>thin</span>":"";
      h+="<tr>"
        +"<td class='who'><span class='strong'>"+r.n+"</span>"+tag+"</td>"
        +"<td class='cat'>"+r.bh+"</td>"
        +"<td class='num'>"+isk(v.buy)+"</td>"
        +"<td class='cat'>"+(r.fh||"n/a")+"</td>"
        +"<td class='num "+(v.flipNet==null?"":cls(v.flipNet))+"'>"+isk(v.flipNet)+"</td>"
        +"<td class='cat'>"+r.lh+"</td>"
        +"<td class='num strong "+cls(v.listNet)+"'>"+isk(v.listNet)+"</td>"
        +"<td class='num "+(v.margin==null?"":cls(v.margin))+"'>"+(v.margin==null?"n/a":Math.round(v.margin)+"%")+"</td>"
        +"<td class='num'>"+m3d(v.m3)+"</td>"
        +"<td class='num strong "+(v.iskm3==null?"":cls(v.iskm3))+"'>"+(v.iskm3==null?"n/a":isk(v.iskm3))+"</td>"
        +"<td class='num'>"+qty(v.vol)+"</td></tr>"; }});
    if(!src.length) h="<tr><td colspan='11' class='empty' style='padding:24px'>No item matches \\""+st.q+"\\".</td></tr>";
    document.getElementById("tb").innerHTML=h;
    Array.prototype.forEach.call(document.querySelectorAll("th[data-sort]"), function(th){{
      var k=th.getAttribute("data-sort"); var old=th.querySelector(".ar"); if(old) old.remove();
      if(k===st.key){{ var s=document.createElement("span"); s.className="ar";
        s.textContent=st.dir<0?"\\u25BC":"\\u25B2"; th.appendChild(s); }} }});
  }}
  Array.prototype.forEach.call(document.querySelectorAll("th[data-sort]"), function(th){{
    th.onclick=function(){{ var k=th.getAttribute("data-sort");
      if(st.key===k) st.dir=-st.dir; else {{ st.key=k; st.dir=(k==="n"||k==="bh"||k==="fh"||k==="lh")?1:-1; }}
      render(); }}; }});
  function bind(id, prop){{ document.getElementById(id).addEventListener("input", function(){{
    st[prop]=parseFloat(this.value)||0; render(); }}); }}
  bind("tax","tax"); bind("broker","broker"); bind("freight","freight"); bind("minvol","minvol");
  document.getElementById("q").addEventListener("input", function(){{ st.q=this.value.trim(); render(); }});
  document.getElementById("tProfit").onclick=function(){{ st.all=false; this.classList.add("on"); document.getElementById("tAll").classList.remove("on"); render(); }};
  document.getElementById("tAll").onclick=function(){{ st.all=true; this.classList.add("on"); document.getElementById("tProfit").classList.remove("on"); render(); }};
  render();
}})();
</script>
<script src="https://crownoak.github.io/wdeve/nav.js"></script>
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
