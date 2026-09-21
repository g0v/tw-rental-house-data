'''S3b：「這戶我們見過沒、上次 detail 是什麼時候」的檔案來源（無 Django）。

house 表停寫之前，這兩個問題都是查 House：前緣掃描用「整頁都是已知物件」收單、
deal591 只對已知物件產事件、sweep 的 seed_mode=new 只排從未 detail 的戶。停寫之後
答案在兩個地方：

  總表 latest(D−1)   全戶最後已知狀態（每晚 snapshotfinal 之後摺出；含已關閉的戶）
  今日 list stub      今天到目前為止各輪看到的戶（含 scratch 裡尚未打包的）

時間軸：D 日 02:10 的日跑先摺 final(D−1) 與 latest(D−1)，之後當日各輪 sweep 與 deals
stage 都拿得到它。前一晚的 latest stage 若沒跑成（flow 中止），往回找最近一份總表，
並把「那份總表的日期之後」每一天的 stub 都併進來——寧可多認得，不可少認得：少認得的
代價是前緣掃描不收單（多翻頁）與重複 detail（多爬），兩者都只是多花流量、不傷資料。
'''
from datetime import date as date_cls, timedelta

from rental import artifacts
from rental.seeding import HouseState, OPENED

LOOKBACK_DAYS = 7


class KnownHouses:
    '''ids：見過的戶；state：{hid: HouseState}（open／detail_crawled_at）。
    不在總表、只在 stub 的戶＝新戶：open、從未 detail。'''

    def __init__(self, ids, state, base_date, stub_days):
        self.ids = ids
        self.state = state
        self.base_date = base_date      # 用到的那份總表日期（None＝沒找到）
        self.stub_days = stub_days      # 併了哪幾天的 stub

    def __contains__(self, hid):
        return hid in self.ids

    def add(self, hid):
        '''同一行程內剛看到的戶（前緣掃描逐頁累積；DB 時代是 pipeline 同步寫入讓它變已知）。'''
        if hid not in self.ids:
            self.ids.add(hid)
            self.state.setdefault(hid, HouseState(open=True))


def load(vendor_short, date_str, bucket=None, lookback_days=LOOKBACK_DAYS):
    day = date_cls.fromisoformat(date_str)
    ids, state, base = set(), {}, None
    for back in range(1, lookback_days + 1):
        d = (day - timedelta(days=back)).isoformat()
        rows = artifacts.read_latest(
            vendor_short, d, bucket,
            columns=['vendor_house_id', 'deal_status', 'last_detail_at'])
        if rows is None:
            continue
        base = d
        for r in rows:
            hid = r['vendor_house_id']
            ids.add(hid)
            state[hid] = HouseState(open=r['deal_status'] == OPENED,
                                    detail_crawled_at=r['last_detail_at'])
        break
    first_stub_day = (date_cls.fromisoformat(base) + timedelta(days=1)) if base \
        else day - timedelta(days=lookback_days)
    stub_days = []
    d = first_stub_day
    while d <= day:
        n = 0
        for stub in artifacts.read_list_stubs(vendor_short, d.isoformat(), bucket):
            n += 1
            hid = stub['vendor_house_id']
            if hid not in ids:
                ids.add(hid)
                state[hid] = HouseState(open=True)
        if n:
            stub_days.append(d.isoformat())
        d += timedelta(days=1)
    return KnownHouses(ids, state, base, stub_days)
