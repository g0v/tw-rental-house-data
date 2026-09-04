'''591「已成交」列表頁的 parser（#229）。

2026 改版後 detail 頁不再帶成交資訊——物件成交即 404，能拿到 200 的頁
`status` 一律 `open`。成交只出現在 `list?shType=clinch` 列表：依成交時間
倒序分頁，Nuxt payload 的 `dealDataList` 每項帶 id／「N天成交」／相對
成交日（今日／昨日／N天前）。這裡只讀 payload，不讀 DOM：DOM 只是同一
份資料的呈現，而 payload 的欄位名對改版較穩。

與 detail parser 相同的紀律：只追 591 今天的版式，改版就地改。
'''
import re
from datetime import date, timedelta

from .util import SimpleNuxtInitParser, unquote_js_string

# 相對成交日 → 天數。591 目前只用這三種寫法（page 600、71 天前仍是
# 「N天前」），出現其他字樣時回 None、由 caller 記 warning
_AGE_WORDS = {'今日': 0, '今天': 0, '昨日': 1, '昨天': 1, '前天': 2}
_AGE_RE = re.compile(r'(\d+)\s*天前')
_DAYS_RE = re.compile(r'(\d+)\s*天')
_ABS_DATE_RE = re.compile(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})')

DEAL_FIELDS = (
    'id', 'url', 'region_name', 'section_name', 'kind_name', 'title',
    'deal_total_day', 'deal_time', 'area', 'price', 'unit',
)


class UnknownDealLayoutError(ValueError):
    '''payload 裡找不到 dealDataList——版式變了或根本不是成交列表頁。

    與 UnknownListLayoutError 同理：不猜、直接算 parse 失敗，讓 queue 留
    下 failed 列、熔斷看得到。空結果（`dealDataList:[]`）不算此類。
    '''


def _nuxt_script(text):
    match = re.search(r'<script[^>]*>(window\.__NUXT__.*?)</script>', text, re.S)
    return match.group(1) if match else None


def _scan_bracket(script, start):
    '''從 start（指向 `[` 或 `{`）掃到配對的閉括號，跳過字串字面值。'''
    depth = 0
    quote = None
    i = start
    while i < len(script):
        ch = script[i]
        if quote:
            if ch == '\\':
                i += 1
            elif ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch in '[{':
            depth += 1
        elif ch in ']}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


_PAIR_RE = re.compile(r'([A-Za-z_$][\w$]*):("(?:[^"\\]|\\.)*"|[^,{}]+)')


def _resolve(token, values):
    token = token.strip()
    if token.startswith('"'):
        return unquote_js_string(token)
    if token in values:
        return values[token]
    if re.fullmatch(r'-?\d+(\.\d+)?', token):
        return token
    # 未知變數名：payload 的 arg 對照表沒有它，當缺值
    return None


def parse_deal_age(text):
    '''相對成交日字串 → 距抓取日的天數；未知寫法回 None。'''
    if text is None:
        return None
    text = str(text).strip()
    if text in _AGE_WORDS:
        return _AGE_WORDS[text]
    match = _AGE_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def parse_deal_date(text, base_date):
    '''相對或絕對成交日 → date；解不出回 None。'''
    age = parse_deal_age(text)
    if age is not None:
        return base_date - timedelta(days=age)
    match = _ABS_DATE_RE.search(str(text or ''))
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    return None


def parse_deal_days(text):
    '''「N天成交」→ N；解不出回 None。'''
    if text is None:
        return None
    match = _DAYS_RE.search(str(text))
    return int(match.group(1)) if match else None


def parse_deal_list(text):
    '''成交列表頁 HTML → list of dict（payload 原值＋正規化欄位）。

    每筆帶 DEAL_FIELDS 的原字串，外加 `house_id`（str）、`deal_age_days`
    （int 或 None）、`n_day_deal`（int 或 None）。空結果頁回 []。
    '''
    script = _nuxt_script(text)
    if not script:
        raise UnknownDealLayoutError('no nuxt init script')
    start = script.find('dealDataList:')
    if start < 0:
        raise UnknownDealLayoutError('no dealDataList in nuxt payload')
    open_at = script.find('[', start)
    close_at = _scan_bracket(script, open_at) if open_at >= 0 else None
    if close_at is None:
        raise UnknownDealLayoutError('unterminated dealDataList')
    body = script[open_at + 1:close_at]

    values = SimpleNuxtInitParser(script).dict
    items = []
    i = 0
    while True:
        obj_start = body.find('{', i)
        if obj_start < 0:
            break
        obj_end = _scan_bracket(body, obj_start)
        if obj_end is None:
            break
        obj = body[obj_start + 1:obj_end]
        raw = {}
        for key, token in _PAIR_RE.findall(obj):
            if key in DEAL_FIELDS:
                raw[key] = _resolve(token, values)
        house_id = str(raw.get('id') or '').strip()
        if not house_id and raw.get('url'):
            house_id = str(raw['url']).rstrip('/').split('/')[-1].split('?')[0]
        raw['house_id'] = house_id
        raw['deal_age_days'] = parse_deal_age(raw.get('deal_time'))
        raw['n_day_deal'] = parse_deal_days(raw.get('deal_total_day'))
        items.append(raw)
        i = obj_end + 1
    return items
