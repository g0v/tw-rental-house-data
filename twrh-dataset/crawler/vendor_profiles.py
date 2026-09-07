'''vendor profile：每個資料源的營運政策（multi-vendor-plan〈營運政策層〉，D6b）。

三層分工——站方特性住 package 的 spider；通用機制（queue／rawpack／
finalize／互斥）住 dataset；**這裡只放 per-vendor 的營運政策**：跑哪些
spider、哪些 stage 要跑、前緣掃描與 deals 的參數、sweep 的速率。
flow.py 依 profile 組 stage 表；新 vendor＝加一個 dict，不改 flow。

資料而非程式碼：值可被同名環境變數覆寫（部署層 tfvars／.env 才是速率
與排程的家，這裡是 repo 內預設）。
'''
import os

PROFILES = {
    '591': {
        'name': '591 租屋網',          # DB Vendor.name（fixture vendors.json）
        'list_spider': 'list591',
        'detail_spider': 'detail591',
        'deal_spider': 'deal591',
        # deals stage（#229）：591 成交只在「已成交」列表，detail 成交即 404
        'has_deals_stage': True,
        'deal_lookback_days': '7',       # env TWRH_DEAL_LOOKBACK_DAYS
        # 前緣掃描：list 排序鍵＝刊登時間、新刊登連續排最前，才能整頁已知即收單
        'supports_frontier': True,
        'frontier_pages': '30',          # env TWRH_SWEEP_PAGES
        'sweep_concurrency': '2',        # env TWRH_SWEEP_CONCURRENCY（白天與使用者共用站方資源）
        'sweep_delay': '0.5',            # env TWRH_SWEEP_DELAY
        'sweep_detail_passes': 2,        # 第二趟只撿第一趟 failed 的重試
        # 互斥：同 queue 同日期 bucket，別人 N 小時內更新過的 in_flight 列即讓路
        'busy_window_hours': '2',
    },
}

ENV_OVERRIDES = {
    'deal_lookback_days': 'TWRH_DEAL_LOOKBACK_DAYS',
    'frontier_pages': 'TWRH_SWEEP_PAGES',
    'sweep_concurrency': 'TWRH_SWEEP_CONCURRENCY',
    'sweep_delay': 'TWRH_SWEEP_DELAY',
}


class VendorProfile:
    def __init__(self, short, data):
        self.short = short
        self._data = data

    def __getattr__(self, key):
        if key.startswith('_'):
            raise AttributeError(key)
        try:
            value = self._data[key]
        except KeyError:
            raise AttributeError(key)
        env_name = ENV_OVERRIDES.get(key)
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]
        return value


def get(short='591'):
    try:
        return VendorProfile(short, PROFILES[short])
    except KeyError:
        raise KeyError('unknown vendor {!r}; known: {}'.format(
            short, ', '.join(sorted(PROFILES))))


def names():
    return sorted(PROFILES)
