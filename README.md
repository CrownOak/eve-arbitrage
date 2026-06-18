# eve-arbitrage

Hub Arbitrage Calculator for the Wealthy Dropouts tool suite.

For a curated watchlist of liquid, haulable items, it fetches buy and sell prices across the five
major trade hubs (Jita, Amarr, Dodixie, Rens, Hek) from Fuzzwork region aggregates, works out the
best cross hub spread per item two ways, and bakes a self contained sortable page.

- **FLIP** model: buy at the cheapest hub, instantly sell into the best buy orders at another hub
  (pays sales tax only). Safe, smaller, available now.
- **LIST** model: carry the item to the dearest other hub and relist it under the market (pays
  broker fee plus sales tax, before freight). Bigger, but you wait and the price can move.

Both are net of fees, never gross. Buy cost uses the robust cheapest 5% sell price so a single
mispriced order cannot invent a fake margin.

The page shows each opportunity as a route (buy hub > sell hub) with the jump count between the two
hubs (from ESI `/route`, cached), and ranks by **ISK per jump** for a full cargo hold, because travel
time is the real constraint. A Model toggle switches LIST vs FLIP; a Route toggle switches Highsec
(safe freighter path) vs Shortest jumps. Tax, broker fee, freight, cargo size and min volume are all
editable on the page; the bake stores raw prices and nets them client side, so the operator tunes
them without a rebuild. ISK per m3 stays available for ranking when distance does not matter.

## Run it

    python arbitrage.py --allow-unlocked     # public plaintext page -> index.html
    python arbitrage.py --refresh            # force the ids + volume caches to rebuild

Pure stdlib plus `cryptography` (only needed for the optional password lock). Live runs reach
`fuzzwork.co.uk` and `esi.evetech.net`.

## Cloud

`.github/workflows/run.yml` runs hourly, persists `ids_cache.json` + `vol_cache.json` +
`routes_cache.json` back to this repo, and publishes the page to `CrownOak/wdeve` at `/arbitrage/`
via the `WDEVE_DEPLOY_KEY` deploy key. Requires repo secrets: `WDEVE_DEPLOY_KEY` (required), `EVE_PAGE_PASSWORD` (optional, unused for
the public page).

## Expand the watchlist

`WATCHLIST` in `arbitrage.py` is a flat list of item names. Add names and the builder resolves and
prices them next run (the ids cache invalidates automatically when the list changes). Ships use
packaged (transport) volume from the `SHIPS` map, not the SDE assembled volume.
