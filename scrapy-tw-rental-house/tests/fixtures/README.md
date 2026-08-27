# Parser fixtures

591 detail pages, saved so the parser tests never touch the network. A house
id stops being valid within weeks, and these keep working after the listing is
gone.

Each file is named after the day it was gathered, `YYYYMMDD-detail-<variant>`.
A fixture is never edited once committed: that it stays frozen is what makes it
a regression test. When 591 changes its HTML again, gather a new set under the
new date, edit `scrapy_twrh/spiders/rental591/detail_raw_parser.py` in place to
read it, and retire the fixtures of the old template together with the parser
release that read them — the parser only ever tracks the template 591 serves
today, past templates live in git history and released packages.

## What is in git

| file | what it covers |
|---|---|
| `20260820-detail-whole-floor.html` | 整層住家 / 房廳衛 pattern / 仲介 + 經紀業 / 管理費 / 陽台 |
| `20260820-detail-suite-rooftop.html` | 獨立套房 / 頂層加蓋 / 公寓 / 租金含水電網路 |
| `20260820-detail-shared-suite-owner.html` | 分租套房 / 屋主直租 / 車位租金 / 不可開伙 / 身份要求不含家庭 |
| `20260820-detail-room-basement.html` | 雅房 / B1 樓層 / 屋主直租 / 租金含管理費 |
| `20260820-detail-room-female-only.html` | 雅房 / 限女生租住 / 591 未提供經緯度 |
| `20260820-detail-room-plain-balcony.html` | 雅房 / 陽台沒有標數量 / 可申請租金補貼 |
| `20260820-detail-parking.html` | 車位，沒有房屋詳情與租住設備區塊 |
| `20260820-detail-not-found.html` | 591 對已下架房源回的 404 頁 |
| `20260827-list-beyond-last-page.html` | 591 的空結果列表頁（`.empty`）——爬取途中頁數縮減後，越界尾頁拿到的回應（HTTP 200） |

## How they were made

Each one started as a real page fetched by plain HTTP, then went through two
steps, both of which were asserted before the file was written:

1. **Prune.** Every element no parser selector reaches is dropped, along with
   Vue's `<!--[-->` markers and every attribute other than `class` (plus
   `style` where `reorder_inline_flex_dom` reads it, and `href` on the map
   link). The assertion is that the parse result is unchanged, which is what
   keeps "minimal" from turning into "different". 130KB becomes 8KB.

2. **Scrub.** Every value that identifies someone is replaced by a synthetic
   one: the title, 屋況介紹, the contact's name, the agency, the phone number,
   the community name and the coordinate. Only 591's own vocabulary is left as
   it was - region names, property types, facility names, labels - because
   that vocabulary is what the parser matches on. The assertion is that the
   parse keeps the same keys, list lengths and dict keys, and that every field
   the scrub does not claim to touch still equals the pruned one.

Nothing here is traceable back to a real listing, and no landlord's copy is in
git.

Two things are worth knowing about the files:

- **They are one long line.** Pretty printing would insert whitespace text
  nodes, and both `deep_text` (which concatenates text nodes) and `self_text`
  (which reads the first one) would then see something the real page never
  had. 591 serves one long line too.
- **The `<script>` at the end is a miniature.** The real nuxt init script is
  40KB, holds copies of the title and 屋況介紹, and is where the coordinate
  lives - `.google-maps-link` only appears once JS has loaded the map, so
  plain HTTP has nothing else to read. It cannot simply be deleted either:
  the coordinate is looked up positionally in the argument list. The
  replacement keeps that shape and deliberately puts a comma inside four of
  the values (an inline style with `rgb(20, 106, 153)`, a thousands
  separator, a comma joined list, `\u` escapes), because splitting those
  apart is what used to shift lat / lng onto the wrong value. Like 591, it
  quotes the coordinate and writes the other numbers bare - reading the
  argument list positionally cannot tell the two apart, so getting it wrong
  goes unnoticed there.

## Gaps

Branches no fixture covers yet, because no listing showed them on 2026-08-20:

- 代理人 contact, next to 屋主 and 仲介
- `整棟` and `1F~3F` floor strings
- a price range, which is what 社會住宅 gets (`min_monthly_price`)
- an obfuscated price / floor / area (`<wc-obfuscate-c-*>` plus an image),
  which 591 stopped serving before 2026-08 — today's parser treats those
  markers as the pre-2026 template and refuses the page with
  `LegacyTemplateError`; the parser that read them lives in git history
