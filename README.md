# CTP Magazine

**Your Gateway into the C-domain.**

CTP Magazine is a daily-updating magazine portal that curates articles from around the internet — space, astronomy, consciousness, near-death experiences, UFOs and UAPs, spirituality, and physics — in the format of a classic science magazine. Think OMNI: hard science and the speculative side by side, big visuals, features and short items, and a sense of wonder about the future. An MSN-style portal, but CTP's own.

Live at **https://ctp-magazine.github.io/**

## What it covers

The magazine covers the C-Domain topics from the CTPVerse — the same ground as the CTP Phase I archive: consciousness, conscience, the C-domain, disclosure, the nature of reality, near-death experiences, out-of-body experiences, dreams, ESP and telepathy, clairvoyance, auras, astrology, crystals, pyramids, crop circles, UFOs, unified field theory, yoga and meditation, and the future of space and interstellar travel.

## How it works

The magazine is a re-syndicating engine. It pulls from **114 verified RSS feeds** — original publishers and news aggregators — and pushes their articles into the portal.

- **GitHub Pages** serves the site (static).
- **GitHub Actions** runs the aggregator every 12 hours: a script fetches all 114 feeds, extracts title, link, excerpt, date and image, dedupes, applies the excerpt rules, and writes `articles.json`.
- The magazine page reads `articles.json` and renders each item as a card: title, source, date, excerpt, and a "Read more" link back to the original.
- A hero rotator at the top cycles through featured articles, each slide linking to the live article — to a full article page on the magazine for full-text sources, off-site to the original for excerpt sources.

No Vercel backend, no database. GitHub Actions + GitHub Pages only.

## The feeds

**114 verified feeds** (see `rss-feeds.md` for the full list):

- **14 full text** — NASA (7 feeds, public domain), ESO (CC BY 4.0), The Conversation (CC BY-ND 4.0), Frontiers (4 journals, CC-BY), PLOS ONE (CC-BY). These are the only feeds where the magazine can carry the whole article.
- **7 abstract + link** — arXiv (title and abstract are CC0; full paper text only where that paper is CC-licensed).
- **93 excerpt + link only** — all commercial publishers and all aggregator feeds (Google News and Bing News topic searches). Title + short excerpt (under 200 words) + prominent link back.

Topic breakdown: Space / Astronomy 27 · UFO / UAP 15 · Consciousness / NDE / Mind / Spirituality 41 · Physics / Preprints 11 · General Science / Futurism / Deep Tech 20.

## Clearance — every feed is vetted

**No feed goes on the list uncleared, no exceptions.** Every feed passed two checks:

1. **Verified live** — fetched and confirmed to return valid RSS/Atom with actual items.
2. **Cleared for republication** — checked for what the magazine is legally allowed to republish, with the licence or terms basis recorded.

Where no full-text licence could be established, the feed is carried as excerpt + link only (the safe default). A feed that looks like a good topic match but cannot be cleared does not go on the list.

## Images

Images are used only where the licence covers them: NASA (public domain), ESO (CC BY 4.0), and CC-BY journals. The hero rotator uses only that safe pool, hand-picked and fully credited — never auto-populated from RSS. Commercial sources' images are not re-hosted. The Conversation's CC licence explicitly excludes images. Everything else gets a text-only card or a CTP-original image.

If a publisher asks for a takedown, the item is removed within 24–48 hours.

## Syndication for bloggers

Many bloggers — on Substack, Blogger, and elsewhere — don't get much traffic, because nobody follows a one-off single blog. The magazine syndicates them: their articles get pushed into the portal, excerpt plus link back, with attribution on every item, reaching an audience they don't get alone.

There is **no open submission form**. Bloggers contact the magazine to set it up, and every feed is vetted by the magazine first before it is added.

## The site

Built on the CTP-EOS template — same format and structure, same 41 themes, same left and right column modules, mobile-friendly throughout. A media player sits at the top of the right column. The footer carries the full privacy, copyright, publication, and syndication information.

## Related

- CTPVerse Dashboard — https://ctpverse.github.io/
- CTP-EOS — https://ctp-eos.github.io/
- CTP Space Systems — https://ctp-space-systems.github.io/
- CTP Music Portal — https://ctp-music.github.io/

## License

The site code in this repository is licensed under the **MIT License** (see `LICENSE`). Article content remains under its original publishers' licences — see `rss-feeds.md` for the republication rule on each feed.
