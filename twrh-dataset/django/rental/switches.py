'''切換階梯的開關（無 Django；crawler 與 django 兩側共用）。'''
import os


def house_db():
    '''house／house_ts 還讀寫不讀寫（S3b：預設不）。

    停寫之後的單一真相是檔案分區：list stub／parsed／deals 分區 → snapshot（每日一檔）
    → 總表 latest（全戶最後已知狀態）。DB 這兩張表的每個讀取點都有檔案版接手：
      pipeline 寫入            → 只落 scratch shard（artifact_sink）
      前緣掃描／deals 的「已知物件」 → rental.known（總表＋今日 stub）
      detail 種子（diff／new／full） → seeding.seeds_from_files／rental.known
      manifest                 → crawlerrequest.manifests 的 partitions 版
      export                   → --source snapshot（S3a）
      synthts／syncstateful／四支雙軌對帳 → 退役（flow 內自印 skip）

    回退＝環境 `TWRH_HOUSE_DB=1`：寫入與 DB 讀取點全部回來。但停寫期間 DB 會缺日，
    回退只在「停寫首夜當場發現問題」時有意義；隔了幾天再回退，synthts／syncstateful
    的時間序列假設就不成立了。
    '''
    return os.environ.get('TWRH_HOUSE_DB', '0') == '1'
